# Coordinate-frame constants

Shared by every iMuninn client (Python, web viewer, C++). The phone keeps sending Apple / Android
native data; clients convert once, at their entry point, with these constants. Definition and
rationale: [docs/dev/11-frame-convention.md](../../docs/dev/11-frame-convention.md).

| File | Contents | Edited by |
|---|---|---|
| `convention.json` | `frame_convention` version (1), frame definitions, the rotations between ARKit / Core Motion / OpenCV axes, IMU sign and unit rules per platform, the rule that picks a camera's optical axes from `rotation_deg` and mirroring | hand |
| `review.json` | Per model, whether a person has checked the dimensions against Apple's drawing (`human`) or they are still as extracted (`auto`, the default) | hand |
| `iphone-frames.json` | Per-model frames (`device`, `magsafe`, `cam_main_optical`, `cam_ultra_wide_optical`, `cam_telephoto_optical`, `cam_front_optical`) read off Apple's dimensional drawings, in **mm**, plus an index from the hardware identifier (`DeviceInfo.model`, e.g. `iPhone18,1`) to the model | `tools/gen-frames.py` from the iphone-frames dataset |

Two different checks are tracked. `verified` on a frame or constant means it was measured on a
real phone (`false` everywhere so far; the test list is in section 5 of the convention doc).
`review.dimensions` on a model means the numbers were compared with the drawing by a person. To
mark a model as checked, add it to `review.json`, run `python3 tools/gen-frames.py` (no arguments),
and commit:

```json
"models": { "iphone-17-pro": { "dimensions": "human", "date": "2026-12-01", "by": "Jinqi" } }
```

The parameter page on the site (`/parameter-definition/`) and `imuninn.hardware` read the result
from `iphone-frames.json`.

Notation: `a_tf_b` is the pose of frame `b` in frame `a` (`p_a = a_tf_b @ p_b`); matrices list the
child frame's axes as columns. Quaternions are `(x, y, z, w)`.

Changing either file: bump `frame_convention` only when a definition changes meaning (not for
added models or corrected measurements), then run `tools/gen-frames.py` (or `tools/gen-proto.sh`)
so the copies in `host/python/src/imuninn/data/` match. When a model's measurements change, also
regenerate the model files the site serves (a review-status change does not need this):

```bash
imuninn hardware export --all --format all -o site/public/parameter-definition/models
```
