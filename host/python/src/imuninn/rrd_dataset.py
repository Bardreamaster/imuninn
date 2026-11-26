"""MCAP folders as Rerun datasets.

    imuninn to-rrd runs/              # convert every .mcap under runs/ to runs/_rerun/*.rrd, nothing else
    imuninn browse runs/              # scan, show the estimate, ask, convert what is missing, open the viewer

The Rerun viewer cannot decode imuninn's protobuf messages from an MCAP file itself, so each
recording goes through the same sink as `imuninn rerun --mcap` once and is saved as a .rrd.
`rerun server -d` then serves the folder of .rrd files as a dataset: the viewer lists one
segment per recording and loads a segment only when it is opened.

The dataset server reads a flat folder, so the .rrd files sit side by side in one output folder
(default ``<root>/_rerun``), named after the MCAP's path below the root with ``/`` -> ``__``
(``run1/top.mcap`` -> ``run1__top.rrd``). The recording id, which the dataset shows as the
segment name, keeps the slashes: ``run1/top``.

By default the video is stored as recorded (H.264 samples, `--video stream`), so a .rrd is about
as large as its MCAP and converts in seconds. `--video decode` stores decoded JPEG frames instead
(`--scale` 1 = full size), which is many times larger and slower; such outputs go to a folder
named after the settings so they never mix with the default ones.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("imuninn.rrd")

DEFAULT_OUT = "_rerun"

# Measured on an M-series MacBook Pro with 1920x1440 H.264 recordings (2026-11):
# output size and conversion time per MCAP byte, by video mode.
_SIZE_RATIO = {"stream": 1.05, "off": 0.05}
_SECONDS_PER_MB = {"stream": 0.2, "off": 0.1, "decode": 2.3}
_PER_FILE_S = 1.5  # process start + imports


@dataclass
class Options:
    video: str = "stream"
    scale: float = 1.0
    frames: str = "unified"
    model: str | None = None

    def out_dir_name(self) -> str:
        """Folder name for this setting: the default is `_rerun`, anything else says what differs."""
        parts = []
        if self.video == "decode":
            parts.append("decode" if self.scale >= 1 else f"decode-scale{self.scale:g}")
        elif self.video == "off":
            parts.append("novideo")
        if self.frames != "unified":
            parts.append(self.frames)
        return DEFAULT_OUT + "".join(f"-{p}" for p in parts)

    def size_ratio(self) -> float:
        if self.video == "decode":
            # JPEG q80 at 1920x1440 ~ 47x the H.264 size, ~16x at half size
            return 47.0 * min(1.0, self.scale) ** 1.5
        return _SIZE_RATIO[self.video]


@dataclass
class Job:
    src: Path
    dst: Path
    recording_id: str
    size: int          # MCAP bytes
    up_to_date: bool


def find_mcaps(root: Path) -> list[Path]:
    """Every .mcap below `root` (sorted), skipping folders that start with `_` or `.` (our outputs)."""
    root = Path(root)
    if root.is_file():
        return [root]
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(("_", ".")))
        out += [Path(dirpath) / f for f in sorted(filenames) if f.lower().endswith(".mcap")]
    return out


def plan(root: Path, out: Path | None = None, opts: Options | None = None, force: bool = False) -> tuple[Path, list[Job]]:
    """The output folder and one job per MCAP under `root` (a folder, or a single file)."""
    opts = opts or Options()
    root = Path(root).expanduser().resolve()
    base = root.parent if root.is_file() else root
    out = Path(out).expanduser().resolve() if out else base / opts.out_dir_name()
    jobs = []
    for src in find_mcaps(root):
        rel = src.relative_to(base).with_suffix("")
        rid = rel.as_posix()
        dst = out / (rid.replace("/", "__") + ".rrd")
        st = src.stat()
        ok = not force and dst.exists() and dst.stat().st_mtime >= st.st_mtime
        jobs.append(Job(src, dst, rid, st.st_size, ok))
    return out, jobs


def estimate(jobs: list[Job], opts: Options, workers: int) -> tuple[int, float]:
    """(output bytes, seconds) for the jobs that still need converting; rough."""
    todo = [j for j in jobs if not j.up_to_date]
    size = int(sum(j.size for j in todo) * opts.size_ratio())
    rate = _SECONDS_PER_MB["decode" if opts.video == "decode" else opts.video]
    secs = sum(j.size / 1e6 * rate + _PER_FILE_S for j in todo) / max(1, min(workers, len(todo) or 1))
    return size, secs


def default_workers(opts: Options) -> int:
    n = os.cpu_count() or 2
    # decoding is CPU-heavy and holds full frames in memory: fewer at once
    return max(1, n // 4 if opts.video == "decode" else n // 2)


def _convert_one(src: str, dst: str, recording_id: str, opts: Options) -> dict:
    import rerun as rr  # type: ignore

    from .rerun_bridge import run_mcap

    part = dst + ".part"
    counts = run_mcap(src, save=part, spawn=False, recording_id=recording_id, model=opts.model,
                      video=opts.video, video_scale=opts.scale, frames=opts.frames)
    rr.disconnect()  # flush and close the file before it is renamed
    os.replace(part, dst)
    return counts


def convert(jobs: list[Job], out: Path, opts: Options, workers: int | None = None, progress=print) -> list[tuple[Job, str]]:
    """Convert the jobs that are not up to date, `workers` at a time. Returns the failures (job, error)."""
    todo = [j for j in jobs if not j.up_to_date]
    if not todo:
        return []
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.rrd.part"):  # left by an interrupted run
        stale.unlink()
    workers = max(1, min(workers or default_workers(opts), len(todo)))
    failed = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_convert_one, str(j.src), str(j.dst), j.recording_id, opts): j for j in todo}
        for i, f in enumerate(as_completed(futs), 1):
            j = futs[f]
            try:
                f.result()
                progress(f"[{i}/{len(todo)}] {j.recording_id} -> {j.dst.name} ({_mb(j.dst.stat().st_size)})")
            except Exception as e:  # keep going: one broken file should not stop the rest
                failed.append((j, f"{type(e).__name__}: {e}"))
                progress(f"[{i}/{len(todo)}] {j.recording_id} FAILED: {type(e).__name__}: {e}")
    progress(f"converted {len(todo) - len(failed)} of {len(todo)} in {time.time() - t0:.0f} s")
    return failed


def summary_text(root: Path, out: Path, jobs: list[Job], opts: Options, workers: int) -> str:
    todo = [j for j in jobs if not j.up_to_date]
    size, secs = estimate(jobs, opts, workers)
    video = {"stream": "H.264 as recorded", "off": "no video",
             "decode": f"decoded JPEG frames at {opts.scale:g}x size"}[opts.video]
    lines = [
        f"found {len(jobs)} MCAP file(s) under {root} ({_mb(sum(j.size for j in jobs))})",
        f"  up to date: {len(jobs) - len(todo)}, to convert: {len(todo)} ({_mb(sum(j.size for j in todo))})",
        f"  video: {video}",
        f"  output folder: {out}",
    ]
    if todo:
        free = shutil.disk_usage(_existing_parent(out)).free
        lines.append(f"  estimated: ~{_mb(size)} of new .rrd files (free: {_mb(free)}), "
                     f"~{_duration(secs)} with {min(workers, len(todo))} worker(s)")
        if size > free:
            lines.append("  WARNING: the estimate is larger than the free space")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Serving the folder as a dataset
# ---------------------------------------------------------------------------


def rerun_executable() -> str:
    """The `rerun` CLI that ships with rerun-sdk (inside the venv's bin/, maybe not on PATH)."""
    path = os.pathsep.join([os.path.join(sys.prefix, "bin"), os.environ.get("PATH", "")])
    exe = shutil.which("rerun", path=path)
    if not exe:
        raise RuntimeError("the `rerun` executable was not found: pip install 'imuninn[rerun]'")
    return exe


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, proc: subprocess.Popen, timeout: float = 30.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"`rerun server` exited with code {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"`rerun server` did not open port {port} within {timeout:.0f} s")


def device_names(jobs: list[Job]) -> list[str]:
    """Entity names (`world/<name>`) the recordings use, for the dataset's layout."""
    from .mcap_io import read_device_info
    from .rerun_bridge import device_entity_name

    names: list[str] = []
    for j in jobs:
        try:
            info = read_device_info(j.src)
        except Exception:
            info = None
        n = device_entity_name(info.device_name if info else None, "replay")
        if n not in names:
            names.append(n)
    return names


def _register_layout(url: str, name: str, devices: list[str], tmp: Path) -> str | None:
    """Give the dataset imuninn's layout and return the dataset's URL, or None when the
    catalog client is missing (``rerun-sdk[catalog]``, ~200 MB with its datafusion / pandas):
    the viewer then starts at the server's dataset list with Rerun's automatic layout."""
    try:
        import rerun as rr  # type: ignore

        from .rerun_bridge import blueprint

        ds = rr.catalog.CatalogClient(url).get_dataset(name)
        rbl = tmp / "imuninn.rbl"
        blueprint(rr, devices).save("imuninn-replay", str(rbl))
        ds.register_blueprint(rbl.as_uri(), "imuninn")
        return f"{url}/dataset/{ds.id}"
    except Exception as e:
        log.info("dataset layout not registered: %s", e)
        return None


def serve(out: Path, name: str, port: int | None = None, viewer: bool = True, devices: list[str] | None = None,
          video: str = "stream", progress=None) -> None:
    """Serve `out` (a flat folder of .rrd) as dataset `name` and open a viewer on it.
    Blocks until the viewer window is closed (or Ctrl-C without a viewer), then stops the server."""
    import tempfile

    progress = progress or (lambda m: print(m, flush=True))
    exe = rerun_executable()
    if subprocess.run([exe, "server", "--help"], capture_output=True).returncode != 0:
        raise RuntimeError("this rerun-sdk has no `rerun server` (dataset browsing): pip install -U rerun-sdk")
    port = port or free_port()
    url = f"rerun+http://127.0.0.1:{port}"
    # Own process groups: `rerun` is a Python launcher that starts the actual binary as a child,
    # and stopping the launcher alone would leave the binary running.
    quiet = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    server = subprocess.Popen([exe, "server", "--host", "127.0.0.1", "-p", str(port), "-d", f"{name}={out}"], **quiet)
    view = None

    def _term(*_):
        raise KeyboardInterrupt

    old = signal.signal(signal.SIGTERM, _term)
    tmp = tempfile.TemporaryDirectory(prefix="imuninn-browse-")
    try:
        _wait_port(port, server)
        target = _register_layout(url, name, devices or ["iphone"], Path(tmp.name))
        if target is None:
            progress("note: pip install 'rerun-sdk[catalog]' to open the dataset directly with the imuninn layout; "
                     f"for now click '{name}' in the viewer's source list")
        if video == "stream" and not shutil.which("ffmpeg"):
            progress("note: no ffmpeg on PATH: the native viewer needs it to play the H.264 video "
                     "(or convert with --video decode)")
        if not viewer:
            progress(f"serving dataset '{name}' at {url} (Ctrl-C to stop); open it with: rerun {target or url}")
            server.wait()
            return
        # own viewer port, so a viewer or other program already on 9876 does not matter
        view = subprocess.Popen([exe, "--port", str(free_port()), target or url], **quiet)
        progress(f"dataset '{name}' at {url}: pick a recording in the viewer; close the viewer to stop")
        view.wait()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, old)
        tmp.cleanup()
        for p in (view, server):
            if p is not None:
                _stop_group(p)


def _stop_group(p: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            p.wait(5)
            return
        except subprocess.TimeoutExpired:
            continue


# ---------------------------------------------------------------------------


def _existing_parent(p: Path) -> Path:
    while not p.exists():
        p = p.parent
    return p


def _mb(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB" if n >= 1e6 else f"{n / 1e3:.0f} kB"


def _duration(s: float) -> str:
    return f"{s / 60:.0f} min" if s >= 90 else f"{max(1, round(s))} s"
