from __future__ import annotations

import argparse
import logging

from . import PROTOCOL_VERSION, __version__


def build_parser() -> argparse.ArgumentParser:
    """The `imuninn` command-line parser (also used to generate the CLI reference)."""
    p = argparse.ArgumentParser(prog="imuninn", description="iMuninn PC client")
    p.add_argument("--version", action="version", version=f"imuninn {__version__} (protocol v{PROTOCOL_VERSION})")
    sub = p.add_subparsers(dest="cmd", required=True)

    ls = sub.add_parser("list", help="discover phones on the local network")
    ls.add_argument("--timeout", type=float, default=2.0)

    def add_target(sp):
        sp.add_argument("target", nargs="?", default="", help="phone name, host, or host:port (default: first phone found)")
        sp.add_argument("--start", action="store_true", help="send SessionControl START after connect")

    w = sub.add_parser("watch", help="print incoming samples as text")
    add_target(w)
    w.add_argument("--stream", default=None, help="only this stream id (default: all)")
    w.add_argument("--every", type=int, default=30, help="print one sample out of N")
    w.add_argument("--raw", action="store_true",
                   help="print pose / IMU as sent (ARKit y-up world, Core Motion accel sign) instead of the unified frames")

    r = sub.add_parser("rerun", help="visualise pose / trajectory / video / depth / IMU / health / audio level live in the Rerun viewer")
    r.add_argument("targets", nargs="*", default=[], metavar="target",
                   help="phone name, host, or host:port; several for a multi-device view (default: first phone found)")
    r.add_argument("--start", action="store_true", help="send SessionControl START after connect")
    r.add_argument("--depth", action="store_true", help="enable the depth stream on the phone(s) first")
    r.add_argument("--no-spawn", action="store_true", help="connect to an already running viewer")
    r.add_argument("--video", choices=("decode", "stream", "off"), default="decode",
                   help="decode: PyAV in this client (default); stream: hand H.264 to the viewer "
                        "(viewer-side ffmpeg, stutters at 60 fps); off")
    r.add_argument("--every", type=int, default=1, help="with --video decode: show one frame out of N")
    r.add_argument("--scale", type=float, default=0.5,
                   help="with --video decode: downscale frames for the viewer (1 = full size)")
    r.add_argument("--buffer-ms", type=float, default=0.0,
                   help="playout buffer: release samples in device-time order this many ms late, "
                        "smoothing bursty Wi-Fi delivery (try 150)")
    r.add_argument("--port", type=int, default=None,
                   help="spawn / connect to a viewer on this port instead of the default 9876 (own viewer)")
    r.add_argument("--points", action="store_true",
                   help="back-project depth into a Points3D cloud on the PC (RGB-coloured with --video decode)")
    r.add_argument("--point-stride", type=int, default=2, help="subsample the depth map for --points")
    r.add_argument("--points-hz", type=float, default=10.0, help="rate cap for --points and the confidence image (0 = every frame)")
    r.add_argument("--no-trajectory", action="store_true", help="do not draw the camera path")
    r.add_argument("--no-blueprint", action="store_true", help="keep the viewer's own layout")
    r.add_argument("--mcap", default=None, help="replay this MCAP file instead of connecting to a phone")
    r.add_argument("--save", default=None, help="write a .rrd file instead of opening the viewer")
    r.add_argument("--seconds", type=float, default=None, help="stop after this long (live mode)")
    r.add_argument("--frames", choices=("unified", "raw"), default="unified",
                   help="unified: z-up world, device and camera optical frames (default); raw: ARKit y-up world as sent")
    r.add_argument("--model", default=None,
                   help='with --mcap: phone model for camera offsets when the file has no /device topic, e.g. "iPhone18,1"')

    def add_rrd_options(sp):
        sp.add_argument("input", help="folder searched recursively for .mcap files (or one .mcap file)")
        sp.add_argument("-o", "--output", default=None,
                        help="folder for the .rrd files (default: <input>/_rerun; other --video / --frames "
                             "settings get their own _rerun-<setting> folder)")
        sp.add_argument("--video", choices=("stream", "decode", "off"), default="stream",
                        help="stream: keep the H.264 video as recorded (default, about the MCAP size); "
                             "decode: store decoded JPEG frames (much larger and slower); off: no video")
        sp.add_argument("--scale", type=float, default=1.0,
                        help="with --video decode: downscale the stored frames (1 = full size, the default)")
        sp.add_argument("--frames", choices=("unified", "raw"), default="unified",
                        help="unified: z-up world, device and camera optical frames (default); raw: ARKit y-up world")
        sp.add_argument("--model", default=None,
                        help='phone model for camera offsets when a file has no /device topic, e.g. "iPhone18,1"')
        sp.add_argument("--force", action="store_true", help="convert again even when the .rrd is newer than the .mcap")
        sp.add_argument("-j", "--jobs", type=int, default=None, help="files converted in parallel (default: half the CPU cores)")

    tr = sub.add_parser("to-rrd", help="convert every .mcap under a folder to Rerun .rrd files (skips up-to-date ones)")
    add_rrd_options(tr)

    br = sub.add_parser("browse", help="browse a folder of .mcap recordings in the Rerun viewer: convert to .rrd "
                                       "after a confirmation, then open them as a dataset (pick one, it plays)")
    add_rrd_options(br)
    br.add_argument("-y", "--yes", action="store_true", help="do not ask before converting")
    br.add_argument("--name", default=None, help="dataset name shown in the viewer (default: the folder name)")
    br.add_argument("--port", type=int, default=None, help="port of the local dataset server (default: a free one)")
    br.add_argument("--no-viewer", action="store_true", help="only run the dataset server; connect a viewer yourself")

    rec = sub.add_parser("record", help="record all subscribed streams to an MCAP file")
    add_target(rec)
    rec.add_argument("-o", "--output", default=None, help="output .mcap (default: imuninn-<time>.mcap)")
    rec.add_argument("--streams", default=None, help="comma-separated stream ids (default: all)")
    rec.add_argument("--depth", action="store_true", help="enable the depth stream before recording")
    rec.add_argument("--audio", action="store_true", help="enable the microphone (audio) stream before recording")

    cv = sub.add_parser("convert", help="convert a phone-side .imuninn recording to MCAP")
    cv.add_argument("input")
    cv.add_argument("-o", "--output", default=None)
    cv.add_argument("--model", default=None,
                    help='phone model stored in the file for camera offsets, e.g. "iPhone18,1" or "iPhone 17 Pro"')

    web = sub.add_parser("web", help="serve the browser viewer at http://localhost:7430 (it connects straight to the phone)")
    web.add_argument("--port", type=int, default=7430)
    web.add_argument("--host", default="127.0.0.1", help="bind address; keep localhost so the browser treats the page as secure")
    web.add_argument("--no-open", action="store_true", help="do not open the default browser")
    web.add_argument("--static", default=None, help="serve this directory instead of the packaged viewer")

    ea = sub.add_parser("export-audio", help="write the audio stream of an MCAP or phone .imuninn recording to a WAV file")
    ea.add_argument("input")
    ea.add_argument("-o", "--output", default=None, help="output .wav (default: <input>.wav)")
    ea.add_argument("--no-fill", action="store_true",
                    help="do not insert silence for missing chunks (the WAV then drifts from the device clock)")

    info = sub.add_parser("info", help="message counts per topic in an MCAP file")
    info.add_argument("input")

    hw = sub.add_parser("hardware", help="iPhone hardware constants: body size, camera / MagSafe frames (no phone needed)")
    hws = hw.add_subparsers(dest="hcmd", required=True)
    hws.add_parser("list", help="models in the packaged dataset, with their hardware identifiers")
    hsh = hws.add_parser("show", help="one model's frames (device_tf_<frame>, metres) and cameras")
    hsh.add_argument("model", help='name or identifier, e.g. "iPhone 17 Pro" or "iPhone18,1"')
    hsh.add_argument("--json", action="store_true", help="print JSON (metres, 4x4 matrices)")
    hsh.add_argument("--mm", action="store_true", help="print the dataset entry as packaged (millimetres, drawing notes) as JSON")
    hex_ = hws.add_parser("export", help="write a URDF / MJCF / glTF (.glb) model with every frame (glb needs imuninn[models])")
    hex_.add_argument("model", nargs="?", default=None, help='name or identifier, e.g. "iPhone 17 Pro"; omit with --all')
    hex_.add_argument("--format", choices=("urdf", "mjcf", "glb", "all"), default="urdf",
                      help="all (with --all): every format into <output>/<format>/ plus a manifest.json")
    hex_.add_argument("-o", "--output", default=".", help="output file or directory (default: current directory)")
    hex_.add_argument("--all", action="store_true", help="every model in the dataset into the output directory")
    hex_.add_argument("--prefix", default="", help="prefix for link / site names (urdf, mjcf), e.g. phone_")

    pr = sub.add_parser("profile", help="apply / save / list YAML configuration presets")
    prs = pr.add_subparsers(dest="pcmd", required=True)
    pa = prs.add_parser("apply", help="apply a built-in profile name or a YAML file to the phone")
    pa.add_argument("profile")
    pa.add_argument("target", nargs="?", default="")
    ps = prs.add_parser("save", help="save the phone's current config as YAML")
    ps.add_argument("-o", "--output", required=True)
    ps.add_argument("target", nargs="?", default="")
    prs.add_parser("list", help="list built-in profiles")

    return p


def main(argv: list[str] | None = None) -> None:
    """Entry point of the `imuninn` command."""
    p = build_parser()
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.cmd == "list":
        _list(args)
    elif args.cmd == "watch":
        _watch(args)
    elif args.cmd == "rerun":
        _rerun(args)
    elif args.cmd == "record":
        _record(args)
    elif args.cmd in ("to-rrd", "browse"):
        _rrd(args)
    elif args.cmd == "convert":
        from .mcap_io import convert

        from .proto import imuninn_pb2 as pb

        out = args.output or str(args.input).rsplit(".", 1)[0] + ".mcap"
        n = convert(args.input, out, device=pb.DeviceInfo(model=args.model, platform=pb.PLATFORM_IOS) if args.model else None)
        print(f"wrote {n} messages to {out}")
    elif args.cmd == "profile":
        _profile(args)
    elif args.cmd == "hardware":
        _hardware(args)
    elif args.cmd == "web":
        from .web import serve

        serve(args.host, args.port, open_browser=not args.no_open, directory=args.static)
    elif args.cmd == "export-audio":
        from .audio import export_wav

        out = args.output or str(args.input).rsplit(".", 1)[0] + ".wav"
        w = export_wav(args.input, out, fill_gaps=not args.no_fill)
        if w.frames == 0:
            print(f"no audio in {args.input}")
        else:
            rate = w.sample_rate
            print(f"wrote {w.frames / rate:.2f} s ({w.frames} frames @ {rate} Hz, {w.gaps} gaps filled) to {out}; "
                  f"first sample at device time {w.first_time_ns} ns")
    elif args.cmd == "info":
        from .mcap_io import summary

        for topic, n in sorted(summary(args.input).items()):
            print(f"{topic:16s} {n}")


def _list(args) -> None:
    from .discovery import discover

    phones = discover(args.timeout)
    if not phones:
        print("no phones found (is the iMuninn app open and on the same Wi-Fi?)")
    for ph in phones:
        others = [a for a in ph.addresses if a != ph.host]
        extra = f"  (also {', '.join(others)})" if others else ""
        print(f"{ph.name:30s} {ph.address:22s} proto v{ph.protocol_version}{extra}")


def _watch(args) -> None:
    from .frames import Imu, Pose
    from .proto import imuninn_pb2 as pb
    from .session import connect

    with connect(args.target, frames="raw" if args.raw else "unified") as dev:
        print(f"connected: {dev!r}")
        if not args.raw:
            print(f"frames: unified ({dev.frames!r}); --raw for the messages as sent")
        if args.start:
            dev.start()
        n = 0
        for stream, sample in dev.iter(None):
            if args.stream and stream != args.stream:
                continue
            n += 1
            if n % args.every:
                continue
            t = sample.header.device_time_ns / 1e9
            if isinstance(sample, Pose):
                p_, q = sample.world_pos_device, sample.world_quat_device
                print(
                    f"{stream} seq={sample.header.seq} t={t:.3f} world_pos_device=({p_[0]:+.3f},{p_[1]:+.3f},{p_[2]:+.3f}) "
                    f"world_quat_device=({q[0]:+.3f},{q[1]:+.3f},{q[2]:+.3f},{q[3]:+.3f}) "
                    f"{pb.TrackingState.Name(sample.tracking)}"
                )
            elif isinstance(sample, Imu):
                a, g = sample.accel, sample.gyro
                print(
                    f"{stream} seq={sample.header.seq} t={t:.3f} "
                    f"a=({a[0]:+.2f},{a[1]:+.2f},{a[2]:+.2f}) g=({g[0]:+.3f},{g[1]:+.3f},{g[2]:+.3f})"
                )
            elif isinstance(sample, pb.PoseSample):
                p_, q = sample.position, sample.orientation
                print(
                    f"{stream} seq={sample.header.seq} t={t:.3f} "
                    f"p=({p_.x:+.3f},{p_.y:+.3f},{p_.z:+.3f}) q=({q.x:+.3f},{q.y:+.3f},{q.z:+.3f},{q.w:+.3f}) "
                    f"{pb.TrackingState.Name(sample.tracking)}"
                )
            elif isinstance(sample, pb.ImuSample):
                a, g = sample.accel, sample.gyro
                print(
                    f"{stream} seq={sample.header.seq} t={t:.3f} "
                    f"a=({a.x:+.2f},{a.y:+.2f},{a.z:+.2f}) g=({g.x:+.3f},{g.y:+.3f},{g.z:+.3f})"
                )
            elif isinstance(sample, pb.DeviceHealth):
                print(
                    f"{stream} seq={sample.header.seq} t={t:.3f} thermal={pb.DeviceHealth.Thermal.Name(sample.thermal).removeprefix('THERMAL_').lower()} "
                    f"battery={sample.battery_level:.2f} {pb.DeviceHealth.BatteryState.Name(sample.battery_state).removeprefix('BATTERY_').lower()} "
                    f"pose={sample.pose_hz:.0f} imu={sample.imu_hz:.0f} video={sample.video_fps:.0f} depth={sample.depth_hz:.0f} audio={sample.audio_hz:.0f} up={sample.uptime_s:.0f}s"
                )
            elif isinstance(sample, pb.DepthFrame):
                from .depth import decode

                d, c = decode(sample)
                valid = d[d > 0]
                print(
                    f"{stream} seq={sample.header.seq} t={t:.3f} {sample.width}x{sample.height} "
                    f"{len(sample.depth_mm)}+{len(sample.confidence)} B "
                    f"range {valid.min() if valid.size else 0}-{valid.max() if valid.size else 0} mm "
                    f"valid {100 * valid.size / d.size:.0f}% fx={sample.intrinsics.fx:.1f}"
                )
            elif isinstance(sample, pb.AudioChunk):
                from .audio import level_dbfs

                print(
                    f"{stream} seq={sample.header.seq} t={t:.3f} {sample.sample_rate} Hz x{sample.channels} "
                    f"{pb.AudioEncoding.Name(sample.encoding).removeprefix('AUDIO_ENCODING_').lower()} "
                    f"{sample.frame_count} frames {level_dbfs(sample):.1f} dBFS"
                )
            elif isinstance(sample, pb.VideoFrame):
                print(
                    f"{stream} seq={sample.header.seq} t={t:.3f} {sample.width}x{sample.height} "
                    f"{'I' if sample.keyframe else 'P'} {len(sample.data)} B rot={sample.rotation_deg} fx={sample.intrinsics.fx:.1f}"
                )
            else:
                print(f"{stream} seq={sample.header.seq} t={t:.3f}")


def _rerun(args) -> None:
    from contextlib import ExitStack

    from .rerun_bridge import run_devices, run_mcap
    from .session import connect

    kw = dict(spawn=not args.no_spawn, save=args.save, use_blueprint=not args.no_blueprint, port=args.port,
              video=args.video, every_nth_video=args.every, video_scale=args.scale, points=args.points,
              point_stride=args.point_stride, points_hz=args.points_hz, trajectory=not args.no_trajectory,
              frames=args.frames)
    if args.mcap:
        counts = run_mcap(args.mcap, model=args.model, **kw)
        print(f"replayed: {counts}")
        return
    with ExitStack() as stack:
        devs = [stack.enter_context(connect(t, frames=args.frames)) for t in (args.targets or [""])]
        for dev in devs:
            print(f"connected: {dev!r}")
            if args.depth:
                dev.set("depth.enabled", True)
            if args.start:
                dev.start()
        if args.seconds:
            import threading

            threading.Timer(args.seconds, lambda: [d.close() for d in devs]).start()
        try:
            run_devices(devs, buffer_ms=args.buffer_ms, **kw)
        except Exception as e:  # queue ends when every device closes
            if any(d.connected for d in devs):
                raise
            print(f"stopped: {e}")


def _rrd(args) -> None:
    import sys
    from pathlib import Path

    from . import rrd_dataset as rd

    root = Path(args.input).expanduser()
    if not root.exists():
        sys.exit(f"not found: {root}")
    opts = rd.Options(video=args.video, scale=args.scale, frames=args.frames, model=args.model)
    out, jobs = rd.plan(root, args.output, opts, force=args.force)
    if not jobs:
        sys.exit(f"no .mcap files under {root}")
    workers = args.jobs or rd.default_workers(opts)
    print(rd.summary_text(root.resolve(), out, jobs, opts, workers))
    todo = [j for j in jobs if not j.up_to_date]
    if args.cmd == "browse" and todo and not args.yes:
        if not sys.stdin.isatty():
            sys.exit("not a terminal: pass --yes to convert without asking")
        if input("convert now and open the viewer? [Y/n] ").strip().lower() not in ("", "y", "yes"):
            sys.exit("cancelled")
    failed = rd.convert(jobs, out, opts, workers)
    for j, err in failed:
        print(f"failed: {j.src}: {err}", file=sys.stderr)
    if args.cmd == "to-rrd":
        if failed:
            sys.exit(1)
        return
    if not any(out.glob("*.rrd")):
        sys.exit("nothing to show")
    name = args.name or (root.resolve().parent if root.is_file() else root.resolve()).name
    rd.serve(out, name, port=args.port, viewer=not args.no_viewer,
             devices=rd.device_names(jobs), video=opts.video)


def _record(args) -> None:
    import time

    from .mcap_io import McapRecorder
    from .proto import imuninn_pb2 as pb
    from .session import connect

    out = args.output or time.strftime("imuninn-%Y%m%d-%H%M%S.mcap")
    with connect(args.target, frames="raw") as dev:   # MCAP stores the messages as sent
        print(f"connected: {dev!r}")
        if args.depth:
            dev.set("depth.enabled", True)
        if args.audio:
            dev.set("audio.enabled", True)
        if args.streams:
            dev.subscribe([s.stream_id for s in dev.capabilities.streams], unsubscribe=True)
            dev.subscribe(args.streams.split(","))
        with McapRecorder(out, dev.info, dev.capabilities, dev.clock_offset_ns) as rec:
            rec.write_config(dev.config)
            dev.on("__event__", lambda e: rec.write_config(dev.config) if e == "config" else None)
            if args.start:
                dev.start()
            print(f"recording to {out} … Ctrl-C to stop")
            t0 = time.time()
            try:
                for stream, sample in dev.iter(None):
                    rec.write(pb.DataMessage(**{_stream_field(sample): sample}))
                    if time.time() - t0 > 5:
                        t0 = time.time()
                        print(f"  {rec.count} messages; " + ", ".join(f"{k} {v.rate_hz:.0f} Hz" for k, v in dev.stats.items()))
            except KeyboardInterrupt:
                pass
        print(f"wrote {rec.count} messages to {out}")


def _hardware(args) -> None:
    import json

    from . import hardware

    if args.hcmd == "list":
        ids: dict[str, list[str]] = {}
        for ident, name in hardware.identifiers().items():
            ids.setdefault(name, []).append(ident)
        for name in hardware.list_models():
            print(f"{name:28s} {', '.join(ids.get(name, [])) or '-'}")
        return
    if args.hcmd == "export":
        from .models import export, export_all, export_bundle

        if args.format == "all":
            if not args.all:
                raise SystemExit("--format all needs --all (it writes every model in every format)")
            manifest = export_bundle(args.output)
            print(f"wrote {len(manifest['models'])} models x {len(manifest['formats'])} formats and manifest.json to {args.output}")
        elif args.all:
            paths = export_all(args.format, args.output)
            print(f"wrote {len(paths)} {args.format} files to {args.output}")
        elif args.model:
            print(f"wrote {export(args.model, args.format, args.output, prefix=args.prefix)}")
        else:
            raise SystemExit("give a model name or --all")
        return
    ph = hardware.get(args.model)
    if args.mm:
        print(json.dumps(ph.raw_mm, indent=1, ensure_ascii=False))
        return
    if args.json:
        print(json.dumps(ph.to_dict(), indent=1))
        return
    w, h, t = ph.size_m
    review = {"auto": "extracted automatically, not checked by a person yet", "human": "checked by a person"}
    print(f"{ph.name}  ({', '.join(ph.identifiers) or 'identifier unknown'})")
    print(f"  dimensions: {review.get(ph.dimensions_review, ph.dimensions_review)}")
    print(f"  body {w * 1e3:.2f} x {h * 1e3:.2f} x {t * 1e3:.2f} mm"
          + (f", camera glass {ph.camera_bump_m * 1e3:.2f} mm above the back" if ph.camera_bump_m else ""))
    print("  frames (device_tf_<frame>: position in device, mm; axes as device directions; source, verified)")
    for f in ph.frames:
        tf = ph.device_tf(f)
        axes = []
        for i in range(3):
            col = tf[:3, i]
            j = int(abs(col).argmax())
            axes.append(f"{'xyz'[i]}={'-' if col[j] < 0 else '+'}{'XYZ'[j]}")
        pv = ph.provenance(f)
        pos = ", ".join(f"{v * 1e3:+8.2f}" for v in tf[:3, 3])
        print(f"  {f:24s} [{pos}]  {' '.join(axes)}  {pv.source}, verified={pv.verified}")
    print("  cameras")
    for c in ph.cameras.values():
        cone = f"keep-out cone {c.keepout_cone_deg} deg" if c.keepout_cone_deg else ""
        print(f"  {c.name:12s} {c.facing:5s} rotation_deg {c.rotation_deg}  {cone}")


def _profile(args) -> None:
    from .profiles import builtin_profiles, resolve_path
    from .session import connect

    if args.pcmd == "list":
        for name in builtin_profiles():
            print(f"{name:16s} {resolve_path(name)}")
        return
    with connect(args.target) as dev:
        if args.pcmd == "apply":
            r = dev.apply_profile(args.profile)
            for f in r.fields:
                status = pb_status(f.status)
                print(f"  {f.key:28s} {status:9s} {f.reason}")
            print(f"config v{r.config_version}{' (session restarted)' if r.session_restarted else ''}")
        elif args.pcmd == "save":
            dev.save_profile(args.output)
            print(f"saved {args.output}")


def pb_status(status) -> str:
    from .proto import imuninn_pb2 as pb

    return pb.ConfigResult.FieldResult.Status.Name(status).removeprefix("STATUS_").lower()


def _stream_field(sample) -> str:
    from .proto import imuninn_pb2 as pb

    return {pb.ImuSample: "imu", pb.PoseSample: "pose", pb.VideoFrame: "video",
            pb.DepthFrame: "depth", pb.Gap: "gap", pb.DeviceHealth: "health", pb.AudioChunk: "audio"}[type(sample)]
