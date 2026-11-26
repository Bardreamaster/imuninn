# Web viewer

See the phone's data in a browser and control the phone: video, depth, pose trajectory, IMU plots, microphone audio (playback and a level plot, protocol v6), thermal state and battery. The page is static, connects straight to the phone (protocol v5), can change every phone parameter and record MCAP, and can also replay an MCAP file offline.

## Online page

**<https://imuninn-webviewer.projects.weijinqi.com>**

- **Safari (macOS / iPadOS / iOS) works as is**: open the page, type the address shown in the app's Server card (e.g. `10.0.0.5`), press Connect.
- **Chrome / Edge cannot reach the phone** from a public page: their security policy blocks LAN addresses and withholds the video decoder. Use one of the two ways below.
- Offline MCAP replay works in every browser.

## Chrome / Edge: serve it locally

```bash
pip install imuninn
imuninn web                 # serves the same page at http://localhost:7430 and opens it
```

Opened from `localhost` the browser treats the page as trusted: video decodes and connections to the phone on the LAN are allowed. The page still talks to the phone directly; this computer only serves the files.

:::caution[Chrome / Edge alternative: a browser flag]
Open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, enter `http://imuninn-webviewer.projects.weijinqi.com`, restart the browser, then open the online page over **http://**. The site is then treated as a secure origin; connecting to the phone shows a one-time "allow local network access" prompt. This is a developer setting, only for your own machine.
:::

## Why

- Chrome / Edge Local Network Access: an http page from a public origin may not reach `10.x` / `192.168.x` addresses; an https page may ask for permission, but then mixed-content rules forbid `ws://`.
- WebCodecs (H.264 decoding) exists only in secure contexts: `https://` and `http://localhost`.
- Safari has neither restriction today; Firefox connects but has no WebCodecs, so the video panel stays empty.

## How the direct connection works

Browsers cannot open raw TCP / UDP, so protocol v5 gives the phone a browser path: the page performs the same control-WebSocket handshake (port 7420) as the Python client with `Hello.data_transport = WEBSOCKET`, then opens a second WebSocket to the same port, sends `"IMDATA01"` + the 4-byte `client_id`, and receives every stream as binary `DataMessage` frames. The data format is identical to Python / C++ (the page parses the same `imuninn.proto` at runtime with protobufjs).

## Controlling the phone

The page is a full client, not only a viewer: everything the Python client can do to the phone is here too (on a direct connection).

| Feature | Where on the page | Python equivalent |
| --- | --- | --- |
| Start / stop capture | "Start capture / Stop" in the Connection card | `dev.start()` / `dev.stop()` |
| Choose which streams to receive | stream chips at the bottom of the Connection card | `dev.subscribe()` |
| Every parameter (session mode, black screen, per-stream switches, IMU rate, camera exposure / white balance / focus / zoom, depth, microphone, ...) | the Phone settings card, grouped by stream | `dev.set("rgb.iso", 400)` |
| Apply / save a profile | the Profile row of the Phone settings card | `imuninn profile apply / save` |
| Config lease | top right of the Phone settings card | `dev.acquire_lease()` / `release_lease()` |
| Re-read parameters and config | Refresh | `dev.get_config()` |
| Time sync | Sync clock | `dev.time_sync()` |
| Phone-side recording (`.imuninn`) | Record on phone | `dev.start_recording()` / `stop_recording()` |
| Record to MCAP | Record MCAP | `imuninn record` |
| Device info, thermal state, battery | the Device card | `dev.info` / `dev.health` |

- **The settings panel is generated from the phone's `Capabilities`**: it lists whatever parameters the phone reports, so a parameter added to the app later shows up without a page change. Parameters tagged "restart" restart the capture session; streams pause briefly.
- After a change the phone's verdict appears next to the control: `✓` applied; "clamped to ..." when the value was out of range and the phone pulled it back; "rejected" comes with the reason and the control returns to the phone's current value. Changes made on the phone or by another client show up here as well.
- **Lease**: one client at a time may change parameters. The page takes the lease on its first change; while another client holds it, changes fail and the log says who holds it. "Release control" gives it up, and disconnecting releases it too.
- **Profiles** are the same YAML files as the Python package (`calibration`, `dataset`, `teleop`, `camera_wide`), or your own file; "Save current config" downloads a YAML that `imuninn profile apply` accepts.
- **Record MCAP** writes the same format as `imuninn record`, readable by `imuninn rerun --mcap`, `imuninn info` and `imuninn export-audio`. Chrome / Edge ask where to save and write to disk while recording; Safari / Firefox lack that API, so the recording stays in memory and downloads on stop: for long recordings use Chrome / Edge or `imuninn record`. Only the streams the page is subscribed to are recorded.

Python command line only: discovery on the local network (`imuninn list`; browsers cannot do mDNS, hence the address field), the Rerun visualisation, `.imuninn` to MCAP conversion, WAV export.

## Browser requirements

- Video: WebCodecs (`VideoDecoder` fed with H.264 Annex‑B): Chrome / Edge 94+ (localhost or https), Safari 16.4+.
- Depth: Apple block LZ4, decoded by a small JS decoder; MCAP zstd chunks via `fzstd`.
- Pose is drawn as a top-down X–Z trajectory with heading (ARKit frame, Y up).

## Build it yourself

```bash
cd host/web && npm install && npm run build      # -> host/web/dist
imuninn web --static host/web/dist
```
