"""Model files for one iPhone, generated from the packaged frame table (:mod:`imuninn.hardware`).

======  ===================================  ==================================================
format  for                                  content
======  ===================================  ==================================================
urdf    ROS, RViz, MoveIt, Isaac Sim import  link ``device`` with box + lens cylinders, inertia;
                                             one link per frame on a fixed joint
mjcf    MuJoCo                               body ``device`` with box / cylinder geoms, inertia;
                                             one site per frame
glb     Blender, three.js, Unity, Isaac      rounded body, lens cylinders, MagSafe ring; one
                                             named empty node per frame
======  ===================================  ==================================================

URDF and MJCF use the standard library only. glb needs ``trimesh`` (``pip install
"imuninn[models]"``). Everything is in metres, in the ``device`` frame (x right edge, y top,
z out of the screen); glTF is y-up, so a phone loaded in a glTF viewer stands upright, screen
toward the viewer.

Geometry is approximate: a box (URDF / MJCF) or a rounded box with an estimated corner radius
(glb) of the drawing's outline, lens windows as cylinders up to the camera glass. The mass is
estimated from the box volume (see :attr:`imuninn.hardware.Phone.mass_kg`). Frames are exact to
the dataset; see :meth:`imuninn.hardware.Phone.provenance` for how far to trust each one.

    from imuninn import hardware
    hardware.export("iPhone 17 Pro", "urdf", "out/")      # -> out/iphone_17_pro.urdf
"""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np

from .frames import rot_to_quat
from . import _data
from .hardware import Phone, get, list_models

FORMATS = ("urdf", "mjcf", "glb")
_EXT = {"urdf": ".urdf", "mjcf": ".xml", "glb": ".glb"}


def model_basename(ph: Phone) -> str:
    """File / robot name: ``iphone_17_pro``."""
    return ph.slug.replace("-", "_")


def _fmt(v: Any) -> str:
    return " ".join(f"{float(x) + 0.0:.9g}" for x in np.atleast_1d(v))   # 9 digits: rpy near pi stays exact to 1e-9


def _rpy(r: np.ndarray) -> np.ndarray:
    """URDF fixed-axis roll-pitch-yaw with R = Rz(yaw) @ Ry(pitch) @ Rx(roll)."""
    if abs(r[2, 0]) < 1 - 1e-9:
        pitch = -math.asin(r[2, 0])
        roll = math.atan2(r[2, 1], r[2, 2])
        yaw = math.atan2(r[1, 0], r[0, 0])
    else:  # gimbal lock: pitch = +-90 deg, put everything in yaw
        pitch = math.copysign(math.pi / 2, -r[2, 0])
        roll = 0.0
        yaw = math.atan2(-r[0, 1], r[1, 1])
    return np.array([roll, pitch, yaw])


def rpy_to_rot(rpy: Any) -> np.ndarray:
    """Inverse of the URDF rpy convention (used by the tests)."""
    r, p, y = rpy
    rx = np.array([[1, 0, 0], [0, math.cos(r), -math.sin(r)], [0, math.sin(r), math.cos(r)]])
    ry = np.array([[math.cos(p), 0, math.sin(p)], [0, 1, 0], [-math.sin(p), 0, math.cos(p)]])
    rz = np.array([[math.cos(y), -math.sin(y), 0], [math.sin(y), math.cos(y), 0], [0, 0, 1]])
    return rz @ ry @ rx


def _body_box(ph: Phone) -> tuple[np.ndarray, np.ndarray]:
    """(centre in device, full size) of the outline box, metres."""
    o, da = ph.raw_mm["outline"], ph.raw_mm["display_active_area"]
    cu = da["left"] + da["width"] / 2
    cv = da["top"] + da["height"] / 2
    centre = np.array([o["width"] / 2 - cu, cv - o["height"] / 2, -o["thickness"] / 2]) * 1e-3
    return centre, np.array(ph.size_m)


def _lenses(ph: Phone) -> list[tuple[str, np.ndarray, float, float]]:
    """Rear lens windows as (camera, xy centre, radius, z of the glass) in metres."""
    out = []
    t = ph.size_m[2]
    for c in ph.cameras.values():
        if c.facing != "back" or not c.window_diameter_m:
            continue
        p = ph.device_tf(c.frame)[:3, 3]
        out.append((c.name, p[:2], c.window_diameter_m / 2, min(p[2], -t)))
    return out


def _box_inertia(mass: float, size: np.ndarray) -> np.ndarray:
    w, h, t = size
    return mass / 12.0 * np.array([h * h + t * t, w * w + t * t, w * w + h * h])


# ---------------------------------------------------------------------------
# URDF
# ---------------------------------------------------------------------------


def to_urdf(ph: Phone, prefix: str = "") -> str:
    """URDF text: link ``<prefix>device`` and one fixed-joint link per frame (plus ``imu``)."""
    robot = ET.Element("robot", name=model_basename(ph))
    ET.SubElement(robot, "material", name="iphone_body").append(ET.Element("color", rgba="0.15 0.15 0.17 1"))
    ET.SubElement(robot, "material", name="iphone_lens").append(ET.Element("color", rgba="0.05 0.05 0.06 1"))
    centre, size = _body_box(ph)
    dev = ET.SubElement(robot, "link", name=prefix + "device")
    for tag in ("visual", "collision"):
        el = ET.SubElement(dev, tag, name="body")
        ET.SubElement(el, "origin", xyz=_fmt(centre), rpy="0 0 0")
        ET.SubElement(ET.SubElement(el, "geometry"), "box", size=_fmt(size))
        if tag == "visual":
            ET.SubElement(el, "material", name="iphone_body")
    t = size[2]
    for name, xy, r, z_glass in _lenses(ph):
        length = -t - z_glass
        if length <= 0:
            continue
        el = ET.SubElement(dev, "visual", name=f"lens_{name}")
        ET.SubElement(el, "origin", xyz=_fmt([xy[0], xy[1], -t - length / 2]), rpy="0 0 0")
        ET.SubElement(ET.SubElement(el, "geometry"), "cylinder", radius=f"{r:.6g}", length=f"{length:.6g}")
        ET.SubElement(el, "material", name="iphone_lens")
    inertial = ET.SubElement(dev, "inertial")
    ET.SubElement(inertial, "origin", xyz=_fmt(centre), rpy="0 0 0")
    ET.SubElement(inertial, "mass", value=f"{ph.mass_kg:.6g}")
    ixx, iyy, izz = _box_inertia(ph.mass_kg, size)
    ET.SubElement(inertial, "inertia", ixx=f"{ixx:.6g}", ixy="0", ixz="0", iyy=f"{iyy:.6g}", iyz="0", izz=f"{izz:.6g}")

    frames = [f for f in ph.frames if f != "device"] + ["imu"]
    for f in frames:
        tf = np.eye(4) if f == "imu" else ph.device_tf(f)
        ET.SubElement(robot, "link", name=prefix + f)
        j = ET.SubElement(robot, "joint", name=f"{prefix}device_to_{f}", type="fixed")
        ET.SubElement(j, "parent", link=prefix + "device")
        ET.SubElement(j, "child", link=prefix + f)
        ET.SubElement(j, "origin", xyz=_fmt(tf[:3, 3]), rpy=_fmt(_rpy(tf[:3, :3])))
    ET.indent(robot)
    head = (f"<?xml version=\"1.0\"?>\n<!-- {ph.name}: generated by imuninn from Apple's dimensional drawings "
            f"(iphone-frames dataset). Frames: device = display centre on the front glass (x right, y top, "
            f"z out of the screen); cam_*_optical = OpenCV axes. Geometry and mass are approximate. -->\n")
    return head + ET.tostring(robot, encoding="unicode") + "\n"


# ---------------------------------------------------------------------------
# MJCF
# ---------------------------------------------------------------------------


def to_mjcf(ph: Phone, prefix: str = "") -> str:
    """MJCF text: one body ``<prefix>device`` with geoms, inertia and a site per frame (no joint:
    attach it to your robot, or add ``<freejoint/>`` to let it fall)."""
    root = ET.Element("mujoco", model=model_basename(ph))
    ET.SubElement(root, "compiler", angle="radian")
    asset = ET.SubElement(root, "asset")
    ET.SubElement(asset, "material", name=prefix + "iphone_body", rgba="0.15 0.15 0.17 1")
    ET.SubElement(asset, "material", name=prefix + "iphone_lens", rgba="0.05 0.05 0.06 1")
    world = ET.SubElement(root, "worldbody")
    body = ET.SubElement(world, "body", name=prefix + "device", pos="0 0 0")
    centre, size = _body_box(ph)
    ET.SubElement(body, "inertial", pos=_fmt(centre), mass=f"{ph.mass_kg:.6g}",
                  diaginertia=_fmt(_box_inertia(ph.mass_kg, size)))
    ET.SubElement(body, "geom", name=prefix + "body", type="box", pos=_fmt(centre), size=_fmt(size / 2),
                  material=prefix + "iphone_body")
    t = size[2]
    for name, xy, r, z_glass in _lenses(ph):
        length = -t - z_glass
        if length <= 0:
            continue
        ET.SubElement(body, "geom", name=f"{prefix}lens_{name}", type="cylinder",
                      pos=_fmt([xy[0], xy[1], -t - length / 2]), size=f"{r:.6g} {length / 2:.6g}",
                      material=prefix + "iphone_lens", mass="0")
    for f in [f for f in ph.frames if f != "device"] + ["imu"]:
        tf = np.eye(4) if f == "imu" else ph.device_tf(f)
        q = rot_to_quat(tf[:3, :3])   # xyzw -> MJCF wxyz below
        ET.SubElement(body, "site", name=prefix + f, pos=_fmt(tf[:3, 3]), quat=_fmt([q[3], q[0], q[1], q[2]]),
                      size="0.002")
    ET.indent(root)
    head = (f"<!-- {ph.name}: generated by imuninn from Apple's dimensional drawings (iphone-frames dataset). "
            f"Sites: device frame (x right, y top, z out of the screen) and cam_*_optical (OpenCV axes). "
            f"Geometry and mass are approximate. -->\n")
    return head + ET.tostring(root, encoding="unicode") + "\n"


# ---------------------------------------------------------------------------
# glTF binary
# ---------------------------------------------------------------------------


def _rounded_rect(w: float, h: float, r: float, n: int = 12) -> np.ndarray:
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


def _extrude_convex(poly: np.ndarray, z0: float, z1: float):
    """Prism over a convex polygon (counter-clockwise), caps triangulated as fans."""
    import trimesh  # type: ignore

    n = len(poly)
    v = np.vstack([np.column_stack([poly, np.full(n, z0)]), np.column_stack([poly, np.full(n, z1)])])
    faces = []
    for i in range(1, n - 1):
        faces.append([0, i + 1, i])               # bottom (faces -z)
        faces.append([n, n + i, n + i + 1])       # top (faces +z)
    for i in range(n):
        j = (i + 1) % n
        faces += [[i, j, n + j], [i, n + j, n + i]]
    return trimesh.Trimesh(vertices=v, faces=np.array(faces), process=True)


def to_glb(ph: Phone) -> bytes:
    """glTF binary: meshes for the body, rear lenses and the MagSafe ring, plus an empty node per frame."""
    try:
        import trimesh  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise ImportError('glb export needs trimesh: pip install "imuninn[models]"') from e

    centre, size = _body_box(ph)
    w, h, t = size
    radius = min(w, h) * 0.15   # estimate: the drawings do not dimension the corner radius
    body = _extrude_convex(_rounded_rect(w, h, radius), -t / 2, t / 2)
    body.apply_translation(centre)
    body.visual.face_colors = [38, 38, 43, 255]
    scene = trimesh.Scene()   # root "world"; "device" is an explicit node so the phone moves as one object
    scene.graph.update(frame_from=scene.graph.base_frame, frame_to="device", matrix=np.eye(4))
    scene.add_geometry(body, node_name="body", geom_name="body", parent_node_name="device")
    for name, xy, r, z_glass in _lenses(ph):
        length = -t - z_glass
        if length <= 0:
            continue
        cyl = trimesh.creation.cylinder(radius=r, height=length, sections=48)
        cyl.apply_translation([xy[0], xy[1], -t - length / 2])
        cyl.visual.face_colors = [13, 13, 15, 255]
        scene.add_geometry(cyl, node_name=f"lens_{name}", geom_name=f"lens_{name}", parent_node_name="device")
    ms = ph.raw_mm["frames"].get("magsafe")
    if ms is not None and ms.get("diameter"):
        # outline of the drawing's MagSafe keep-out circle (not the magnet ring itself)
        p = ph.device_tf("magsafe")[:3, 3]
        r_out = ms["diameter"] / 2 * 1e-3
        ring = trimesh.creation.annulus(r_min=r_out - 0.0015, r_max=r_out, height=0.0003, sections=96)
        ring.apply_translation([p[0], p[1], p[2] - 0.00015])
        ring.visual.face_colors = [200, 200, 205, 255]
        scene.add_geometry(ring, node_name="magsafe_ring", geom_name="magsafe_ring", parent_node_name="device")
    for f in ph.frames:
        if f == "device":
            continue
        scene.graph.update(frame_from="device", frame_to=f, matrix=ph.device_tf(f))
    scene.graph.update(frame_from="device", frame_to="imu", matrix=np.eye(4))
    scene.metadata["name"] = ph.name
    return scene.export(file_type="glb")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def export(ph: Phone | str, fmt: str, path: Any, prefix: str = "") -> Path:
    """Write one model file; `path` is a file or an existing / new directory (then the file is
    ``<dir>/iphone_17_pro.urdf`` etc.). Returns the written path."""
    if isinstance(ph, str):
        ph = get(ph)
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}")
    out = Path(path)
    if out.is_dir() or str(path).endswith(("/", "\\")) or not out.suffix:
        out.mkdir(parents=True, exist_ok=True)
        out = out / (model_basename(ph) + _EXT[fmt])
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "urdf":
        out.write_text(to_urdf(ph, prefix))
    elif fmt == "mjcf":
        out.write_text(to_mjcf(ph, prefix))
    else:
        out.write_bytes(to_glb(ph))
    return out


def export_all(fmt: str, directory: Any) -> list[Path]:
    """Every model in the dataset into `directory` (what the release attachments are built from)."""
    return [export(name, fmt, Path(directory)) for name in list_models()]


def data_fingerprint() -> str:
    """SHA-256 over what the model files depend on: every model's entry in the frame table except
    its ``review`` status. A bundle is current when its manifest carries the same value."""
    models = {slug: {k: v for k, v in m.items() if k != "review"} for slug, m in _data.iphone_frames()["models"].items()}
    return hashlib.sha256(json.dumps(models, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def export_bundle(directory: Any, formats: tuple[str, ...] = FORMATS) -> dict:
    """Every model in every format, ready to publish: ``<directory>/<format>/<model>.<ext>`` plus
    ``<directory>/manifest.json`` listing each model's files and sizes (what the site's parameter
    page builds its download buttons from). Returns the manifest."""
    root = Path(directory)
    manifest: dict = {
        "generator": "imuninn.models.export_bundle",
        "frame_convention": _data.iphone_frames()["frame_convention"],
        "data_sha256": data_fingerprint(),
        "units": "m",
        "note": "Frames match protocol/frames/iphone-frames.json. Geometry is approximate (a box, or a rounded box "
                "with an estimated corner radius in glb) and the mass is estimated from the volume.",
        "formats": {fmt: _EXT[fmt] for fmt in formats},
        "models": {},
    }
    for name in list_models():
        ph = get(name)
        files = {}
        for fmt in formats:
            path = export(ph, fmt, root / fmt)
            files[fmt] = {"path": f"{fmt}/{path.name}", "bytes": path.stat().st_size}
        manifest["models"][ph.slug] = {"name": ph.name, "files": files}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    return manifest
