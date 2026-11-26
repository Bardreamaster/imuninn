# Rerun

```bash
pip install "imuninn[rerun]"
imuninn rerun --start                    # first phone found, spawn the Rerun Viewer, start capture
imuninn rerun iPhone --depth --points    # depth on, back-projected into a point cloud on the PC
imuninn rerun phoneA phoneB              # several phones in one viewer
imuninn rerun --mcap run1.mcap           # replay a recording
imuninn rerun --save run1.rrd iPhone     # write a .rrd instead of opening a window
```

## Layout in the viewer

One subtree per phone (`<dev>` is the device name), in the [unified frames](11-frames.md): `world` is z up.

| entity | content |
| --- | --- |
| `world/<dev>` | device pose `world_tf_device` |
| `world/<dev>/trajectory` | path of the device origin |
| `world/<dev>/cam` + `/video` | lens optical frame `device_tf_cam_*_optical` + pinhole camera + image |
| `world/<dev>/depth/image`, `/confidence` | depth (metres) and confidence, in the main camera's optical frame |
| `world/<dev>/depth_points` | depth back-projected to points (`--points`, coloured from RGB) |
| `plots/<dev>/imu/*`, `pose/tracking`, `health/*` | IMU plots, tracking state, thermal / battery / rates |
| `events/<dev>` | tracking / thermal / low-power changes, drops, config changes |

Timelines: `pc` (wall clock, shared by all phones) and `device` (the phone's monotonic clock).

`--frames raw` restores the pre-0.3 view: the y-up ARKit world, `world/<dev>` = the ARKit camera, points at `world/<dev>/points`. When replaying an MCAP without a `/device` topic, `--model "iPhone 17 Pro"` names the phone; otherwise lens offsets are 0.

## Options

| option | effect |
| --- | --- |
| `--video decode` (default) | decode with PyAV on this machine and send images; steady 60 fps |
| `--video stream` | hand H.264 to the viewer; the native viewer needs `ffmpeg` on PATH and stutters at 1920×1440@60 |
| `--every N` | decode one frame in N to save CPU |
| `--scale 0.5` | downscale decoded frames for the viewer (default 0.5; intrinsics scaled to match) |
| `--buffer-ms 150` | playout buffer: release samples in device-time order N ms late, smoothing bursty Wi‑Fi delivery |
| `--points` / `--point-stride` / `--points-hz` | point cloud, its subsampling stride, and the rate cap for points and the confidence image (default 10 Hz) |
| `--no-trajectory` / `--no-blueprint` | no trajectory / keep the viewer's own layout |
| `--port` | use your own viewer port (default 9876) |
| `--seconds N` | stop after N seconds |

Every option: [CLI reference](07-cli.md#imuninn-rerun).

## Browsing a folder of recordings

```bash
imuninn browse ~/recordings        # scan, estimate, confirm, convert, then list every recording in the viewer
imuninn to-rrd ~/recordings        # convert only, no viewer
```

The viewer cannot read imuninn's protobuf messages, so each `.mcap` first goes through the same processing as `imuninn rerun --mcap` and is saved as a `.rrd`. `browse` then serves the `.rrd` files to the viewer as one dataset with `rerun server -d`: the window shows a list of recordings, and a recording is loaded only when you open it.

- **Scan**: `.mcap` files anywhere below the input folder; subfolders starting with `_` or `.` are skipped (the output lives in one).
- **Confirm**: `browse` first prints how many files it found, how many are already up to date, the estimated new disk space and time, and where the output goes, and converts only after you press Enter. `-y` skips the question and is required when not running in a terminal. `to-rrd` never asks.
- **Output**: `<input>/_rerun/` by default, one flat folder (the dataset server reads a single level). `run1/top.mcap` becomes `run1__top.rrd` and is listed as `run1/top`. `-o` puts it elsewhere.
- **Incremental**: a `.rrd` newer than its `.mcap` is skipped; `--force` converts everything again. `*.rrd.part` files left by an interrupted run are removed on the next run.
- **Quality**: the default `--video stream` keeps the H.264 video exactly as recorded, so a `.rrd` is about as large as its MCAP and converts in seconds; the native viewer needs `ffmpeg` on PATH to play it. `--video decode` stores decoded JPEG frames (`--scale` defaults to 1, full size), tens of times larger and much slower; `--video off` stores no video. Non-default settings write to their own folders (`_rerun-decode`, `_rerun-novideo`, ...) so they never mix with the default output.
- **Layout**: with `rerun-sdk[catalog]` installed (about 200 MB with datafusion and pandas), `browse` registers imuninn's layout on the dataset and opens the recording list directly. Without it the viewer starts at the server's dataset list (click the dataset name) and recordings use Rerun's automatic layout.
- Closing the viewer window ends the command. `--no-viewer` only runs the dataset server and prints the address to open with `rerun <address>`.
