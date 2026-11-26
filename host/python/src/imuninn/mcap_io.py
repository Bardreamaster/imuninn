"""MCAP recording / conversion / replay (§7.3): the phone's Protobuf messages are
written as-is, one topic per stream, so the dataset format *is* the protocol.

    imuninn record [phone] -o run1.mcap      # live from a phone
    imuninn convert rec.imuninn -o rec.mcap  # phone-side recording -> MCAP
    imuninn replay run1.mcap                 # iterate; `imuninn rerun --mcap run1.mcap` to view

Topics: /imu (ImuSample), /ar_pose (PoseSample), /rgb (VideoFrame), /depth (DepthFrame),
/audio (AudioChunk), /gap (Gap), /config (ConfigChanged). log_time = PC wall clock (when recording live) or
device time (when converting); publish_time = device monotonic time, always.

Messages are stored exactly as the phone sent them (Apple native frames). Files written by this
package also carry an MCAP metadata record "imuninn" with "frame_convention" (and the package and
protocol versions); files without it (older recordings, converted phone files before 0.3) read as
frame_convention 0, which converts the same way. `replay()` yields pose / IMU in the unified frames
by default (imuninn.frames); `replay(..., frames="raw")` and `replay_timed()` give the messages as stored.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterator

from .proto import imuninn_pb2 as pb

log = logging.getLogger("imuninn.mcap")

MAGIC = b"IMUNINN1"
METADATA_NAME = "imuninn"

_TOPIC_TO_CLASS = {
    "/imu": "ImuSample", "/ar_pose": "PoseSample", "/rgb": "VideoFrame", "/depth": "DepthFrame",
    "/gap": "Gap", "/config": "ConfigChanged", "/device": "DeviceInfo", "/capabilities": "Capabilities",
    "/health": "DeviceHealth", "/audio": "AudioChunk",
}

_BODY_TO_TOPIC = {
    "imu": "/imu",
    "pose": "/ar_pose",
    "video": "/rgb",
    "depth": "/depth",
    "gap": "/gap",
    "config_changed": "/config",
    "health": "/health",
    "audio": "/audio",
}


class McapRecorder:
    """Write phone messages to an MCAP file, one topic per stream, Protobuf-encoded as received.

    Use as a context manager; feed :meth:`write` from a data listener. ``log_time`` is PC
    wall clock when ``clock_offset_ns`` is known, ``publish_time`` is device time.
    """

    def __init__(self, path: str | Path, device: pb.DeviceInfo | None = None,
                 capabilities: pb.Capabilities | None = None, clock_offset_ns: int | None = None):
        from mcap_protobuf.writer import Writer  # type: ignore

        self.path = Path(path)
        self._f = open(self.path, "wb")
        self._w = Writer(self._f)
        self.count = 0
        self.clock_offset_ns = clock_offset_ns
        self._w.add_metadata(METADATA_NAME, _metadata(device))
        if device is not None:
            self._w.write_message("/device", device, log_time=time.time_ns(), publish_time=0)
        if capabilities is not None:
            self._w.write_message("/capabilities", capabilities, log_time=time.time_ns(), publish_time=0)

    def write(self, msg: pb.DataMessage, log_time_ns: int | None = None) -> None:
        """Append one ``DataMessage`` to its topic."""
        body = msg.WhichOneof("body")
        if body is None:
            return
        sample = getattr(msg, body)
        has_header = hasattr(sample, "header")
        publish = sample.header.device_time_ns if has_header else 0
        if log_time_ns is None:
            if self.clock_offset_ns is not None and has_header:
                log_time_ns = publish + self.clock_offset_ns
            else:
                log_time_ns = time.time_ns()
        self._w.write_message(_BODY_TO_TOPIC[body], sample, log_time=log_time_ns, publish_time=publish)
        self.count += 1

    def write_config(self, config: pb.DeviceConfig) -> None:
        """Record the configuration in effect on the ``/config`` topic."""
        self.write(pb.DataMessage(config_changed=pb.ConfigChanged(config=config)))

    def close(self) -> None:
        """Finish the MCAP index and close the file."""
        self._w.finish()
        self._f.close()

    def __enter__(self) -> "McapRecorder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _metadata(device: pb.DeviceInfo | None) -> dict[str, str]:
    from . import PROTOCOL_VERSION, __version__
    from .frames import FRAME_CONVENTION

    md = {"frame_convention": str(FRAME_CONVENTION), "imuninn_version": __version__,
          "protocol_version": str(PROTOCOL_VERSION)}
    if device is not None:
        md["device_model"] = device.model
        md["phone_frame_convention"] = str(getattr(device, "frame_convention", 0))
    return md


def read_metadata(path: str | Path) -> dict[str, str]:
    """The file's "imuninn" metadata record ({} for files written before 0.3)."""
    from mcap.reader import make_reader  # type: ignore

    with open(path, "rb") as f:
        for rec in make_reader(f).iter_metadata():
            if rec.name == METADATA_NAME:
                return dict(rec.metadata)
    return {}


def read_frame_convention(path: str | Path) -> int:
    """``frame_convention`` recorded in the file, 0 when absent (recorded before 0.3)."""
    return int(read_metadata(path).get("frame_convention", 0))


def read_phone_recording(path: str | Path) -> Iterator[pb.DataMessage]:
    """Iterate a phone-side `.imuninn` recording (magic + length-prefixed DataMessage)."""
    with open(path, "rb") as f:
        if f.read(8) != MAGIC:
            raise ValueError(f"{path}: not an iMuninn recording")
        while True:
            head = f.read(4)
            if len(head) < 4:
                return
            n = int.from_bytes(head, "little")
            payload = f.read(n)
            if len(payload) < n:
                return
            msg = pb.DataMessage()
            msg.ParseFromString(payload)
            yield msg


def convert(src: str | Path, dst: str | Path, device: pb.DeviceInfo | None = None) -> int:
    """Phone recording -> MCAP. log_time = device time (no PC clock available).

    Phone recordings carry no DeviceInfo; pass `device` (e.g. ``DeviceInfo(model="iPhone18,1")``)
    to store one on ``/device`` so replays know the model for camera offsets."""
    with McapRecorder(dst, device=device) as rec:
        for msg in read_phone_recording(src):
            body = msg.WhichOneof("body")
            sample = getattr(msg, body)
            t = sample.header.device_time_ns if hasattr(sample, "header") else 0
            rec.write(msg, log_time_ns=t)
        return rec.count


def replay(path: str | Path, realtime: bool = False, topics: list[str] | None = None,
           frames: str = "unified", model: str | None = None) -> Iterator[tuple[str, object]]:
    """Yield (stream_id, sample) from an MCAP file. `realtime=True` sleeps to reproduce timing.

    `frames="unified"` (default): pose and IMU samples come as :class:`imuninn.frames.Pose` /
    :class:`imuninn.frames.Imu`, using the model from the file's ``/device`` topic (live
    recordings) or `model` (needed for files converted from phone recordings, which have no
    ``/device``; without it the camera offsets are 0 and a warning is logged).
    `frames="raw"`: every message as stored."""
    from .frames import check_mode

    conv = frame_converter(path, model) if check_mode(frames) == "unified" else None
    for stream, sample, _ in replay_timed(path, realtime=realtime, topics=topics):
        yield stream, (conv.convert(sample) if conv is not None else sample)


def frame_converter(path: str | Path, model: str | None = None):
    """:class:`imuninn.frames.FrameConverter` for a recording (its ``/device`` info, or `model`)."""
    from .frames import FRAME_CONVENTION, FrameConverter

    fc = read_frame_convention(path)
    if fc > FRAME_CONVENTION:
        log.warning("%s was written with frame_convention %d, this package knows %d: update imuninn",
                    path, fc, FRAME_CONVENTION)
    return FrameConverter.from_device_info(read_device_info(path), model=model)


def read_device_info(path: str | Path) -> pb.DeviceInfo | None:
    """The DeviceInfo written at the start of a live recording (None for converted phone files)."""
    from mcap.reader import make_reader  # type: ignore

    with open(path, "rb") as f:
        for schema, channel, message in make_reader(f).iter_messages(topics=["/device"]):
            info = pb.DeviceInfo()
            info.ParseFromString(message.data)
            return info
    return None


def replay_timed(path: str | Path, realtime: bool = False, topics: list[str] | None = None) -> Iterator[tuple[str, object, int]]:
    """Yield (stream_id, sample, log_time_ns): log_time is PC wall clock for live recordings,
    device time for files converted from phone-side recordings."""
    from mcap_protobuf.decoder import DecoderFactory  # type: ignore
    from mcap.reader import make_reader  # type: ignore

    with open(path, "rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        t_first = None
        wall0 = time.monotonic()
        for schema, channel, message, decoded in reader.iter_decoded_messages(topics=topics):
            if channel.topic in ("/device", "/capabilities"):
                continue
            if realtime:
                if t_first is None:
                    t_first = message.log_time
                target = wall0 + (message.log_time - t_first) / 1e9
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
            # mcap_protobuf decodes into classes built from the file's schema; re-parse into
            # this package's generated classes so isinstance() checks work downstream.
            cls_name = _TOPIC_TO_CLASS.get(channel.topic)
            if cls_name is not None:
                sample = getattr(pb, cls_name)()
                sample.ParseFromString(decoded.SerializeToString())
            else:
                sample = decoded
            stream = sample.header.stream_id if hasattr(sample, "header") else channel.topic.strip("/")
            yield stream, sample, message.log_time


def summary(path: str | Path) -> dict[str, int]:
    """Message count per topic, from the file's summary section."""
    from mcap.reader import make_reader  # type: ignore

    with open(path, "rb") as f:
        reader = make_reader(f)
        s = reader.get_summary()
        if s is None:
            return {}
        counts: dict[str, int] = {}
        for cid, st in s.statistics.channel_message_counts.items():
            counts[s.channels[cid].topic] = st
        return counts
