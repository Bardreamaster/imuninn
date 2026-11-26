"""Unified coordinate frames (``frame_convention`` 1).

The phone sends Apple / Android native data. This module converts it once, at the client's
entry point, into one set of robotics-style frames:

====================  ==========================================================================
``world``             origin where the AR session started; **z up**, x = camera heading at session
                      start (horizontal), y left (FLU, REP 103)
``device``            centre of the display active area on the front glass; Core Motion axes:
                      x right edge, y top edge, z out of the screen (portrait)
``imu``               same as ``device``; accelerometer in m/s² with the REP 145 sign (flat, screen
                      up: z = +9.81), gyroscope in rad/s
``cam_*_optical``     OpenCV axes of the *native* (unrotated) image: x right, y down, z forward;
                      origin on the lens window. Intrinsics, pixels and depth live here.
====================  ==========================================================================

Naming: ``a_tf_b`` is the 4×4 pose of frame b in frame a (``p_a = a_tf_b @ p_b``), ``a_rot_b``
its rotation, ``a_pos_b`` its translation, ``a_quat_b`` the rotation as ``(x, y, z, w)``. Chains
read left to right: ``world_tf_cam = world_tf_device @ device_tf_cam``. Units: m, rad, s.

The constants come from ``protocol/frames/convention.json`` (packaged as ``imuninn/data``);
per-model camera positions from the iphone-frames dataset (:mod:`imuninn.hardware`). Nothing in
either has been verified on a phone yet: see each entry's ``verified`` flag.

Typical use is implicit (``imuninn.connect()`` yields :class:`Pose` / :class:`Imu` for the
``ar_pose`` / ``imu`` streams), or explicit::

    conv = FrameConverter.from_device_info(dev.info)
    pose = conv.pose(pose_sample)          # Pose: world_tf_device, raw_arkit_transform, ...
    imu = conv.imu(imu_sample)             # Imu: accel (REP 145), gyro, raw_accel, ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import _data
from .proto import imuninn_pb2 as pb

log = logging.getLogger("imuninn.frames")

FRAME_CONVENTION = 1
"""Version of the frame definitions this package converts to (``DeviceInfo.frame_convention``)."""

FRAMES_MODES = ("unified", "raw")

_CONV = _data.convention()
G = float(_CONV["imu"]["g"])


def _rot(name: str) -> np.ndarray:
    m = np.array(_CONV["rotations"][name]["matrix"], dtype=float)
    m.setflags(write=False)
    return m


WORLD_ROT_AR = _rot("world_rot_ar")
"""ARKit world (y up) -> ``world`` (z up)."""
DEVICE_ROT_ARCAM = _rot("device_rot_arcam")
"""ARKit camera frame (x right, y up, z back in landscape) -> ``device``."""
ARCAM_ROT_OPTICAL = _rot("arcam_rot_optical")
"""OpenCV optical frame -> ARKit camera frame: ``diag(1, -1, -1)``."""
DEVICE_ROT_REAR_OPTICAL = _rot("device_rot_rear_optical")
"""Back-camera optical frame (``rotation_deg`` 90) -> ``device``."""
DEVICE_ROT_FRONT_OPTICAL = _rot("device_rot_front_optical")
"""Front-camera optical frame, ``rotation_deg`` 90 (iPhone 17 Pro), unmirrored -> ``device``."""

CAMERAS = ("main", "ultra_wide", "telephoto", "front")
"""Camera names used by this package and :mod:`imuninn.hardware`."""

# VideoFrame / DepthFrame.camera values (protocol v7) -> camera names above.
_WIRE_CAMERAS = {
    "back_wide": "main", "back_ultra_wide": "ultra_wide", "back_telephoto": "telephoto", "front": "front",
    "main": "main", "wide": "main", "ultra_wide": "ultra_wide", "ultraWide": "ultra_wide", "telephoto": "telephoto",
}


# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------


def make_tf(rot: Any = None, pos: Any = None) -> np.ndarray:
    """4×4 homogeneous transform from a 3×3 rotation and a translation (either may be omitted)."""
    t = np.eye(4)
    if rot is not None:
        t[:3, :3] = np.asarray(rot, dtype=float)
    if pos is not None:
        t[:3, 3] = np.asarray(pos, dtype=float).reshape(3)
    return t


def inv_tf(a_tf_b: np.ndarray) -> np.ndarray:
    """``b_tf_a`` from ``a_tf_b`` (rigid transform: R^T, -R^T p). Also correct for a reflection."""
    r = a_tf_b[:3, :3]
    p = a_tf_b[:3, 3]
    r_inv = np.linalg.inv(r)
    return make_tf(r_inv, -r_inv @ p)


def tf_rot(a_tf_b: np.ndarray) -> np.ndarray:
    """Rotation part ``a_rot_b``."""
    return np.array(a_tf_b[:3, :3])


def tf_pos(a_tf_b: np.ndarray) -> np.ndarray:
    """Translation part ``a_pos_b``."""
    return np.array(a_tf_b[:3, 3])


def quat_to_rot(q_xyzw: Any) -> np.ndarray:
    """Unit quaternion ``(x, y, z, w)`` -> 3×3 rotation (normalised first)."""
    x, y, z, w = (float(v) for v in q_xyzw)
    n = np.sqrt(x * x + y * y + z * z + w * w)
    if n == 0:
        return np.eye(3)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def rot_to_quat(rot: Any) -> np.ndarray:
    """3×3 rotation -> unit quaternion ``(x, y, z, w)`` with ``w >= 0``."""
    m = np.asarray(rot, dtype=float)
    if np.linalg.det(m) < 0:
        raise ValueError("not a rotation (det < 0): a mirrored camera frame has no quaternion")
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w, x, y, z = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w, x, y, z = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w, x, y, z = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s
    q = np.array([x, y, z, w])
    q /= np.linalg.norm(q)
    return -q if q[3] < 0 else q


def xyzw_to_wxyz(q: Any) -> np.ndarray:
    """``(x, y, z, w)`` -> ``(w, x, y, z)`` (MuJoCo, Isaac Sim)."""
    x, y, z, w = q
    return np.array([w, x, y, z], dtype=float)


def wxyz_to_xyzw(q: Any) -> np.ndarray:
    """``(w, x, y, z)`` -> ``(x, y, z, w)`` (ROS, SciPy)."""
    w, x, y, z = q
    return np.array([x, y, z, w], dtype=float)


def tf_from_pos_quat(pos: Any, quat_xyzw: Any) -> np.ndarray:
    """4×4 transform from a translation and an ``(x, y, z, w)`` quaternion."""
    return make_tf(quat_to_rot(quat_xyzw), pos)


def pos_quat_from_tf(a_tf_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(a_pos_b, a_quat_b)`` from a 4×4 transform; the quaternion is ``(x, y, z, w)``."""
    return tf_pos(a_tf_b), rot_to_quat(a_tf_b[:3, :3])


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------


def camera_facing(camera: str) -> str:
    """``"front"`` for the front camera, else ``"back"``."""
    return "front" if camera == "front" else "back"


def camera_name(wire: str | None, default: str = "main") -> str:
    """Camera name (``main`` / ``ultra_wide`` / ``telephoto`` / ``front``) from a
    ``VideoFrame.camera`` value such as ``"back_wide"``; ``default`` when empty or unknown."""
    if not wire:
        return default
    return _WIRE_CAMERAS.get(wire, default)


def device_rot_optical(camera: str = "main", rotation_deg: int | None = None, mirrored: bool = False) -> np.ndarray:
    """Optical axes of a camera's native image, expressed in ``device`` (``device_rot_cam_optical``).

    Args:
        camera: ``"main"``, ``"ultra_wide"``, ``"telephoto"`` (back) or ``"front"``; or the
            facings ``"back"`` / ``"front"``.
        rotation_deg: Clockwise rotation that makes the native image upright in portrait
            (``VideoFrame.rotation_deg``). Defaults to 90 for both facings (iPhone 17 Pro).
        mirrored: The buffer is horizontally mirrored (``VideoFrame.mirrored``). The result then
            includes that reflection (det = -1): it still maps rays back-projected from the
            mirrored image with its own intrinsics into ``device``, but it is not a rotation and
            has no quaternion. Prefer un-mirroring the image (``u -> W - 1 - u``, ``cx -> W - cx``).
    """
    facing = camera if camera in ("back", "front") else camera_facing(camera)
    co = _CONV["camera_optical"]
    if rotation_deg is None:
        rotation_deg = co["default_rotation_deg"][facing]
    up = co["upright"][facing]
    xu, yu, z = np.array(up["x"], float), np.array(up["y"], float), np.array(up["z"], float)
    r = int(rotation_deg) % 360
    axes = {0: (xu, yu), 90: (yu, -xu), 180: (-xu, -yu), 270: (-yu, xu)}
    if r not in axes:
        raise ValueError(f"rotation_deg must be 0, 90, 180 or 270, got {rotation_deg}")
    x, y = axes[r]
    if mirrored:
        x = -x
    return np.column_stack([x, y, z])


def device_tf_camera(model: str | None, camera: str = "main", rotation_deg: int | None = None,
                     mirrored: bool = False, *, warn: bool = True) -> np.ndarray:
    """``device_tf_cam_<camera>_optical``: the camera's optical frame in ``device``.

    The orientation follows ``rotation_deg`` / ``mirrored`` (see :func:`device_rot_optical`); the
    position comes from the iphone-frames dataset for ``model`` (hardware identifier such as
    ``"iPhone18,1"`` or a name such as ``"iPhone 17 Pro"``). Unknown model or camera: position 0
    and a warning (``warn=False`` to silence it).
    """
    from . import hardware

    pos = np.zeros(3)
    ph = hardware.find(model) if model else None
    if ph is not None and f"cam_{camera}_optical" in ph.frames:
        pos = ph.device_tf(f"cam_{camera}_optical")[:3, 3]
    elif warn:
        what = f"model {model!r}" if ph is None else f"camera {camera!r} on {ph.name}"
        log.warning("no frame data for %s: camera position set to the device origin", what if model else "unknown model")
    return make_tf(device_rot_optical(camera, rotation_deg, mirrored), pos)


# ---------------------------------------------------------------------------
# IMU
# ---------------------------------------------------------------------------


def _platform_key(platform: Any) -> str:
    if platform in (pb.PLATFORM_ANDROID, "android"):
        return "android"
    return "ios"   # PLATFORM_IOS, unspecified (old recordings were all iOS)


def imu_to_ros(sample: pb.ImuSample, platform: Any = None) -> tuple[np.ndarray, np.ndarray]:
    """``(accel, gyro)`` in the ``imu`` frame: accelerometer as specific force in m/s² (REP 145,
    flat screen-up z = +9.81), gyroscope in rad/s. iOS sends Core Motion's sign (gravity vector),
    so its accel is negated; Android already sends specific force."""
    key = _platform_key(platform)
    sa = _CONV["imu"]["accel"][key]["scale"]
    sg = _CONV["imu"]["gyro"][key]["scale"]
    a, g = sample.accel, sample.gyro
    return np.array([a.x, a.y, a.z]) * sa + 0.0, np.array([g.x, g.y, g.z]) * sg + 0.0   # + 0.0: no -0.0


# ---------------------------------------------------------------------------
# AR pose
# ---------------------------------------------------------------------------


def ar_tf_arcam(sample: pb.PoseSample) -> np.ndarray:
    """The pose exactly as sent: ARKit ``ARCamera.transform`` (camera in the y-up AR world)."""
    p, q = sample.position, sample.orientation
    return tf_from_pos_quat([p.x, p.y, p.z], [q.x, q.y, q.z, q.w])


def device_tf_arcam(model: str | None, camera: str = "main", *, warn: bool = True) -> np.ndarray:
    """The ARKit camera frame in ``device``: axes from :data:`DEVICE_ROT_ARCAM`, origin at the AR
    tracking camera's lens (main camera by default)."""
    pos = tf_pos(device_tf_camera(model, camera, warn=warn))
    return make_tf(DEVICE_ROT_ARCAM, pos)


def world_tf_device(sample: pb.PoseSample, model: str | None = None, camera: str = "main", *,
                    warn: bool = True) -> np.ndarray:
    """``world_tf_device`` from an ARKit pose: ``world_tf_ar @ ARCamera.transform @ arcam_tf_device``."""
    return make_tf(WORLD_ROT_AR) @ ar_tf_arcam(sample) @ inv_tf(device_tf_arcam(model, camera, warn=warn))


# ---------------------------------------------------------------------------
# Converted samples
# ---------------------------------------------------------------------------


@dataclass
class Pose:
    """An ``ar_pose`` sample in the unified frames. ``raw`` is the PoseSample as received."""

    header: pb.Header
    world_tf_device: np.ndarray
    """4×4 pose of ``device`` in ``world`` (z up)."""
    world_tf_camera: np.ndarray
    """4×4 pose of the AR tracking camera's optical frame (OpenCV axes) in ``world``."""
    camera: str
    """Which camera ARKit tracked with (``"main"`` unless the phone reports otherwise)."""
    tracking: int
    intrinsics: pb.Intrinsics
    raw: pb.PoseSample = field(repr=False)

    @property
    def device_time_ns(self) -> int:
        return self.header.device_time_ns

    @property
    def world_pos_device(self) -> np.ndarray:
        """Device position in ``world``, metres."""
        return tf_pos(self.world_tf_device)

    @property
    def world_rot_device(self) -> np.ndarray:
        return tf_rot(self.world_tf_device)

    @property
    def world_quat_device(self) -> np.ndarray:
        """Device orientation in ``world`` as ``(x, y, z, w)``."""
        return rot_to_quat(self.world_rot_device)

    @property
    def raw_arkit_transform(self) -> np.ndarray:
        """``ARCamera.transform`` as sent (y-up AR world, ARKit camera axes)."""
        return ar_tf_arcam(self.raw)

    @property
    def raw_position(self) -> np.ndarray:
        p = self.raw.position
        return np.array([p.x, p.y, p.z])

    @property
    def raw_orientation(self) -> np.ndarray:
        """Raw ARKit quaternion ``(x, y, z, w)``."""
        q = self.raw.orientation
        return np.array([q.x, q.y, q.z, q.w])


@dataclass
class Imu:
    """An ``imu`` sample in the ``imu`` frame. ``raw`` is the ImuSample as received."""

    header: pb.Header
    accel: np.ndarray
    """Specific force, m/s², REP 145 sign (flat, screen up: z = +9.81)."""
    gyro: np.ndarray
    """Angular rate, rad/s, right-handed about the device axes."""
    mag: np.ndarray
    """Magnetic field, µT, device axes (all zero if the phone does not send it)."""
    raw: pb.ImuSample = field(repr=False)

    @property
    def device_time_ns(self) -> int:
        return self.header.device_time_ns

    @property
    def raw_accel(self) -> np.ndarray:
        """Accelerometer as sent (iOS: Core Motion sign, flat screen-up z = -9.81)."""
        a = self.raw.accel
        return np.array([a.x, a.y, a.z])

    @property
    def raw_gyro(self) -> np.ndarray:
        g = self.raw.gyro
        return np.array([g.x, g.y, g.z])


class FrameConverter:
    """Converts one device's samples into the unified frames.

    Built from the phone's ``DeviceInfo`` (model for camera offsets, platform for the IMU sign,
    AR capture camera); ``model`` overrides the reported one, e.g. for a recording that has no
    ``/device`` topic. :attr:`imuninn.Device.frames` holds the one for a live connection.
    """

    def __init__(self, model: str | None = None, platform: Any = None, ar_camera: str | None = None,
                 frame_convention: int = 0):
        from . import hardware

        self.model = model or None
        self.platform = platform
        self.frame_convention = frame_convention
        self.hardware = hardware.find(model) if model else None
        self.ar_camera = ar_camera or _CONV["ar_tracking_camera"]["default"]
        if frame_convention > FRAME_CONVENTION:
            log.warning("phone reports frame_convention %d, this package knows %d: update imuninn",
                        frame_convention, FRAME_CONVENTION)
        if self.hardware is None:
            log.warning("no frame data for model %r: camera and AR offsets set to 0 (pass model=... to override)",
                        model or "unknown")
        self._device_tf_arcam = device_tf_arcam(self.hardware.slug if self.hardware else None, self.ar_camera, warn=False)
        self._arcam_tf_device = inv_tf(self._device_tf_arcam)
        self._world_tf_ar = make_tf(WORLD_ROT_AR)
        self._arcam_tf_optical = make_tf(ARCAM_ROT_OPTICAL)

    @classmethod
    def from_device_info(cls, info: pb.DeviceInfo | None, model: str | None = None) -> "FrameConverter":
        """Converter for the device described by ``info`` (``None``: unknown iOS device)."""
        if info is None:
            return cls(model=model)
        cap_type = getattr(info, "ar_capture_device_type", "") or ""
        ar_cam = _CONV["ar_tracking_camera"]["capture_device_types"].get(cap_type)
        return cls(model=model or info.model, platform=info.platform, ar_camera=ar_cam,
                   frame_convention=getattr(info, "frame_convention", 0))

    @property
    def model_name(self) -> str | None:
        """Dataset name of the model (``"iPhone 17 Pro"``), or ``None`` when unknown."""
        return self.hardware.name if self.hardware else None

    def __repr__(self) -> str:
        return f"<FrameConverter {self.model_name or self.model or 'unknown model'} ar_camera={self.ar_camera}>"

    # -- conversions ----------------------------------------------------------

    def pose(self, sample: pb.PoseSample) -> Pose:
        """ARKit ``PoseSample`` -> :class:`Pose` in ``world`` (z up)."""
        ar_tf_cam = ar_tf_arcam(sample)
        w_tf_arcam = self._world_tf_ar @ ar_tf_cam
        return Pose(
            header=sample.header,
            world_tf_device=w_tf_arcam @ self._arcam_tf_device,
            world_tf_camera=w_tf_arcam @ self._arcam_tf_optical,
            camera=self.ar_camera,
            tracking=sample.tracking,
            intrinsics=sample.intrinsics,
            raw=sample,
        )

    def imu(self, sample: pb.ImuSample) -> Imu:
        """``ImuSample`` -> :class:`Imu` (REP 145 accel sign, m/s², rad/s)."""
        accel, gyro = imu_to_ros(sample, self.platform)
        m = sample.mag
        return Imu(header=sample.header, accel=accel, gyro=gyro, mag=np.array([m.x, m.y, m.z]), raw=sample)

    def convert(self, sample: Any) -> Any:
        """:class:`Pose` / :class:`Imu` for pose and IMU samples; anything else is returned as is."""
        if isinstance(sample, pb.PoseSample):
            return self.pose(sample)
        if isinstance(sample, pb.ImuSample):
            return self.imu(sample)
        return sample

    def device_tf_camera(self, camera: str = "main", rotation_deg: int | None = None, mirrored: bool = False) -> np.ndarray:
        """``device_tf_cam_<camera>_optical`` for this model (see :func:`device_tf_camera`)."""
        return device_tf_camera(self.hardware.slug if self.hardware else None, camera, rotation_deg, mirrored, warn=False)

    def frame_camera(self, frame: pb.VideoFrame | pb.DepthFrame) -> str:
        """Camera a video / depth frame came from: the frame's ``camera`` field when the phone sends
        it (protocol v7), else the main camera (depth is registered to it)."""
        if isinstance(frame, pb.DepthFrame):
            return camera_name(getattr(frame, "camera", ""), self.ar_camera)
        return camera_name(getattr(frame, "camera", ""), "main")

    def device_tf_frame(self, frame: pb.VideoFrame | pb.DepthFrame) -> np.ndarray:
        """Optical frame of a video / depth frame's native image in ``device``, from its camera,
        ``rotation_deg`` and ``mirrored`` fields."""
        return self.device_tf_camera(self.frame_camera(frame), frame.rotation_deg or None,
                                     bool(getattr(frame, "mirrored", False)))


def check_mode(frames: str) -> str:
    if frames not in FRAMES_MODES:
        raise ValueError(f"frames must be one of {FRAMES_MODES}, got {frames!r}")
    return frames
