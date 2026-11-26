# iMuninn Web Viewer

Static browser viewer for iMuninn phone data: H.264 video (WebCodecs), LiDAR depth, pose
trajectory, IMU plots and device health, straight from the phone (protocol v5: control
WebSocket + a second WebSocket carrying DataMessage frames), or offline by dropping an MCAP
recording onto the page. Hosted at http://imuninn-webviewer.projects.weijinqi.com (http only:
browsers block ws:// from https pages). User docs: `docs/web/01-web-viewer.md`.

```bash
npm install
npm run build        # -> dist/, deploy to any http static host (GitHub Pages)
npm run dev          # Vite dev server on :5173; type the phone's address in the page
```

Layout: `src/proto.ts` parses `protocol/imuninn.proto` at runtime (protobufjs), `video.ts`
(WebCodecs), `lz4.ts` + `depth.ts` (Apple block LZ4), `mcap.ts` (`@mcap/core`), `phone.ts`
(direct phone connection and the control API, mirroring `imuninn.PhoneClient`), `params.ts`
(settings panel generated from the phone's `Capabilities`), `profiles.ts` (the Python
package's YAML presets), `recorder.ts` (MCAP recording, same layout as `imuninn record`),
`live.ts` (relay WebSocket), `plots.ts`, `main.ts` (UI).

The page is a full client: every control the Python client has (parameters, profiles, config
lease, time sync, phone-side recording, MCAP recording) is available on a direct connection.
