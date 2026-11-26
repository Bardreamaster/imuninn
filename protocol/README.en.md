# iMuninn protocol

[中文](README.md)

`imuninn.proto` is the single source of truth for the phone, the PC and every language binding. A protocol change updates all sides in one commit and bumps `VERSION`.

Field reference (generated): `docs/protocol/messages.md`.

## Versions

There are two levels:

| level | where | changes when |
| --- | --- | --- |
| protocol version (an integer, now 7, written v7 in the docs) | the `VERSION` file; `Header.protocol_version` in every message, plus `Hello`, `Welcome` and `DeviceInfo` | a compatible change: plus 1 each time |
| package name (`imuninn.v1`) | `package` in `imuninn.proto` | an incompatible change: becomes `imuninn.v2` |

Rules:

1. **Adding optional fields, messages or enum values bumps the integer by 1.** Old clients ignore fields they do not know, and new clients reading old data see the default (0, empty string, `false`), so a new field's default must mean "not reported".
2. **Removing a field, changing a field number or type, or changing what an existing field means moves the package to `v2`.** None of that happens inside `v1`: unused fields become `reserved`, field numbers are never reused, and a change of meaning is made by adding a new field and leaving the old one as it was.
3. **Clients gate a feature on "version ≥ N"; the two sides need not be equal.** Different versions are the normal case, since the app and the PC side update separately. The Python package and the web viewer only log one `protocol mismatch` line and keep working.

The protocol version is independent of the app and Python package versions (such as 0.2.0). The coordinate-frame convention has its own integer, `frame_convention` (see [Coordinate frames](#coordinate-frames)); redefining frames does not always need a protocol change.

What each version added (the values of N):

| version | added |
| --- | --- |
| v3 | `health` stream (`DeviceHealth`) |
| v4 | `DeviceConfig.session_params` |
| v5 | `Hello.data_transport`, data streams over WebSocket (browsers) |
| v6 | `audio` stream (`AudioChunk`) |
| v7 | frame-convention metadata: `DeviceInfo.frame_convention` / `ar_capture_device_type`, `camera` / `mirrored` on `VideoFrame` / `DepthFrame` |

## Channels

| channel | transport | messages | loss policy |
| --- | --- | --- | --- |
| control | WebSocket | `ControlMessage` | reliable |
| IMU / pose / health | UDP (phone → each client's port), one `DataMessage` per datagram | `ImuSample`, `PoseSample`, `DeviceHealth` | may drop |
| video | TCP | `VideoFrame` (H.264 Annex-B) | sender keeps only the newest frame |
| depth | TCP | `DepthFrame` (uint16 mm + LZ4; zstd reserved) | never drops |
| audio | TCP (v6) | `AudioChunk` (PCM s16 / f32, mono; timestamp = first frame) | never drops |
| all data (browsers) | WebSocket (v5, `Hello.data_transport = WEBSOCKET`) | as above, one `DataMessage` per frame | like TCP: a video backlog drops non-key frames |

Framing on TCP: `uint32 little-endian length` + `DataMessage` bytes. On UDP each datagram is one `DataMessage`, never fragmented (anything larger than the MTU goes over TCP).

## Connection flow (the phone is the server)

1. The phone advertises the Bonjour service `_imuninn._tcp` (name = device name, TXT `proto=<version>`) and listens on control port 7420 (WebSocket) and data port 7422 (TCP).
2. The PC discovers the phone or is given its address, opens the control WebSocket and sends `Hello` (client name, the port it receives UDP on); the phone answers `Welcome` (device info, capabilities + current configuration, TCP port, `client_id`).
3. The PC connects to the phone's TCP data port, writes the 4-byte LE `client_id`, then receives video / depth. Pose / IMU / health are sent by the phone to the PC's UDP port.
   Browsers have no raw TCP / UDP: with `Hello.data_transport = TRANSPORT_WEBSOCKET` the client opens a second WebSocket to the control port, sends binary `"IMDATA01"` + the 4-byte LE `client_id` as its first frame, and then receives every subscribed stream as binary `DataMessage` frames on that connection.
4. `Subscribe` picks streams; `SessionControl START` starts capture. Several PCs can connect at once, each with its own subscriptions.
5. Configuration changes use `SetConfig` (partial update + `base_config_version`) → `ConfigResult` → `ConfigChanged` broadcast to every client. Only the client holding the lease (`Lease`) may change the configuration at a time.

## Coordinate frames

Everything on the wire stays in the platform's native frames; the phone converts nothing:

- Poses are ARKit's `ARCamera.transform`: right-handed, world Y up, the camera looks down −Z.
- IMU samples are in the Core Motion device frame (portrait: x right, y up, z out of the screen) with the platform's accelerometer sign (flat on iOS z ≈ −9.81, on Android ≈ +9.81).
- Images are sent in sensor orientation; `rotation_deg` says how far to rotate clockwise for display, and intrinsics are in the same orientation as the image. Since v7 each frame also names its lens (`camera`) and whether it is mirrored (`mirrored`).

Clients convert once, at their entry point, to the unified frames with the shared constants in `protocol/frames/` (`world` z up, `device`, `cam_*_optical` with OpenCV axes, IMU per REP 145). Since v7 the phone reports the convention version in `DeviceInfo.frame_convention` (currently 1) and the AR tracking camera in `ar_capture_device_type`. The Python package outputs the unified frames by default; see [Python · Coordinate frames](../docs/en/python/11-frames.md).

## Code generation

```bash
tools/gen-proto.sh
```

Generates Python, C++, Swift and Java bindings and copies `imuninn.proto` into the Python package. The Python bindings are committed (installs need no protoc; CI checks them against the `.proto`); generated code for the other languages is not.
