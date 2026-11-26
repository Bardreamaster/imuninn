#!/usr/bin/env python3
"""Export the iphone-frames dataset into protocol/frames/iphone-frames.json.

The dataset (Apple dimensional drawings -> raw/*.yaml -> build_frames.py -> frames/all.json)
lives outside this repository because it carries Apple's PDFs. This script turns its all.json
into the table every iMuninn client reads (and copies it, with convention.json, into the Python
package's imuninn/data/): keyed by dataset slug, with an index from the
hardware identifier (DeviceInfo.model, e.g. "iPhone18,1") to the slug, and frame names that
follow protocol/frames/convention.json (device, magsafe, cam_main_optical, ...).

    python3 tools/gen-frames.py path/to/iphone-frames/frames/all.json   # regenerate from the dataset
    python3 tools/gen-frames.py                                         # only re-apply review.json

protocol/frames/review.json (hand-edited) says, per model, whether a person has checked the
dimensions against the drawing ("human") or they are still as extracted ("auto"). Both modes copy
that status into each model's "review" entry; the second one needs no dataset, so marking a model
as checked is: edit review.json, run this script without arguments, commit.

Lengths stay in millimetres, as on the drawings; the Python package converts to metres.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "protocol" / "frames" / "iphone-frames.json"
REVIEW = ROOT / "protocol" / "frames" / "review.json"
SOURCE = ("iphone-frames dataset: Apple Accessory Design Guidelines dimensional drawings (each model's drawing.url); "
          "values extracted automatically, then checked by a person model by model (each model's review.dimensions)")
PKG_DATA = ROOT / "host" / "python" / "src" / "imuninn" / "data"   # shipped copy (also refreshed by tools/gen-proto.sh)

FRAME_NAMES = {
    "body": "device",
    "magsafe": "magsafe",
    "rear_main": "cam_main_optical",
    "rear_ultra_wide": "cam_ultra_wide_optical",
    "rear_telephoto": "cam_telephoto_optical",
    "front_camera": "cam_front_optical",
}
CAMERA_NAMES = {"rear_main": "main", "rear_ultra_wide": "ultra_wide", "rear_telephoto": "telephoto", "front_camera": "front"}


def _dumps(obj, indent: int = 0) -> str:
    """JSON with one key per line but number lists (vectors, matrices) kept on one line."""
    pad = " " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = [f'{pad} {json.dumps(k)}: {_dumps(v, indent + 1)}' for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(obj, list) and all(isinstance(x, (int, float, list)) and not isinstance(x, bool) for x in obj):
        return json.dumps(obj, separators=(", ", ": "))
    if isinstance(obj, list):
        if not obj:
            return "[]"
        return "[\n" + ",\n".join(f"{pad} {_dumps(x, indent + 1)}" for x in obj) + "\n" + pad + "]"
    return json.dumps(obj, ensure_ascii=False)


def provenance(key: str, f: dict) -> str:
    """drawing = dimensioned on Apple's drawing; role_inferred = position on the drawing, lens role
    inferred from the keep-out cone; estimated = position estimated (front cameras of most models)."""
    if key == "body":
        return "definition"
    if key == "front_camera":
        return "estimated" if "estimated" in (f.get("source") or "") else "drawing"
    if key.startswith("rear_") and "inferred" in (f.get("role_basis") or ""):
        return "role_inferred"
    return "drawing"


def convert_model(slug: str, m: dict) -> dict:
    frames = {}
    cameras = {}
    for key, f in m["frames"].items():
        name = FRAME_NAMES[key]
        out = {
            "origin": f["origin_in_body"],
            "R": f["R_body_frame"],
            "definition": f["definition"],
            "provenance": provenance(key, f),
        }
        for k in ("source", "note", "diameter", "role_basis", "drawing_label", "orientation"):
            if f.get(k) is not None:
                out[k] = f[k]
        # The device frame is a definition. Everything else is read off a drawing (or estimated) and
        # has not been measured on a phone.
        out["verified"] = key == "body"
        frames[name] = out
        if key in CAMERA_NAMES:
            cam = {"frame": name, "facing": "front" if key == "front_camera" else "back"}
            for k in ("window_diameter", "keepout_cone_deg", "keepout_cone_base_in_body", "drawing_label", "role_basis"):
                if f.get(k) is not None:
                    cam["keepout_cone_base" if k == "keepout_cone_base_in_body" else k] = f[k]
            cameras[CAMERA_NAMES[key]] = cam
    out = {
        "name": m["model"],
        "identifiers": m.get("identifiers", []),
        "outline": m["outline"],
        "display_active_area": m["display_active_area"],
        "rear_heights_from_back": m.get("rear_heights_from_back"),
        "drawing": m["drawing"],
        "frames": frames,
        "cameras": cameras,
    }
    for k in ("extras", "identifiers_note", "also_covers", "notes", "unfolded"):
        if m.get(k):
            out[k] = m[k]
    return out


def apply_review(models: dict) -> dict[str, int]:
    """Set every model's "review" entry from review.json; returns how many models have each status."""
    review = json.loads(REVIEW.read_text())
    statuses = set(review["statuses"])
    unknown = set(review["models"]) - set(models)
    if unknown:
        raise SystemExit(f"review.json names models that are not in the dataset: {sorted(unknown)}")
    counts: dict[str, int] = {}
    for slug, m in models.items():
        entry = review["models"].get(slug, {})
        status = entry.get("dimensions", review["default"])
        if status not in statuses:
            raise SystemExit(f"review.json: {slug}: dimensions must be one of {sorted(statuses)}, got {status!r}")
        m["review"] = {"dimensions": status, **{k: entry[k] for k in ("date", "by", "note") if entry.get(k)}}
        counts[status] = counts.get(status, 0) + 1
    return counts


def main(argv: list[str]) -> int:
    if len(argv) > 2 or (len(argv) == 2 and argv[1] in ("-h", "--help")):
        print(__doc__)
        return 2
    if len(argv) == 2:
        src = json.loads(Path(argv[1]).read_text())
        models = {slug: convert_model(slug, m) for slug, m in sorted(src.items())}
        identifiers = {i: slug for slug, m in models.items() for i in m["identifiers"]}
        conventions = {m.get("frame_convention") for m in src.values()}
        if conventions != {1}:
            raise SystemExit(f"dataset frame_convention {conventions}, expected {{1}} (camera frames must be optical)")
        doc = {
            "format": 1,
            "frame_convention": 1,
            "units": "mm",
            "source": SOURCE,
            "frame_names": "protocol/frames/convention.json",
            "models": models,
            "identifiers": dict(sorted(identifiers.items(), key=lambda kv: [int(x) for x in kv[0].removeprefix("iPhone").split(",")])),
        }
    else:   # no dataset: keep the measurements, refresh only the review status
        doc = json.loads(OUT.read_text())
        doc["source"] = SOURCE
        models, identifiers = doc["models"], doc["identifiers"]
    counts = apply_review(models)
    OUT.write_text(_dumps(doc) + "\n")
    PKG_DATA.mkdir(parents=True, exist_ok=True)
    for f in ("iphone-frames.json", "convention.json"):
        (PKG_DATA / f).write_bytes((OUT.parent / f).read_bytes())
    print(f"{OUT.relative_to(ROOT)}: {len(models)} models, {len(identifiers)} identifiers, review {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
