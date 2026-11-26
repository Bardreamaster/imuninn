"""iPhone hardware constants, no phone or network needed.

Body size and the poses of the camera, MagSafe and device frames for 30 iPhone models (iPhone 12
to iPhone 18 Pro / Duo), read off Apple's dimensional drawings (the iphone-frames dataset,
packaged as ``imuninn/data/iphone-frames.json``), plus the frame-convention constants::

    from imuninn import hardware

    hardware.list_models()                      # ["iPhone 12", ..., "iPhone 17 Pro", ...]
    ph = hardware.get("iPhone18,1")             # hardware identifier or name ("iPhone 17 Pro")
    ph.size_m                                   # (width, height, thickness)
    ph.frames                                   # ("device", "magsafe", "cam_main_optical", ...)
    ph.device_tf("cam_main_optical")            # 4x4 numpy array: device_tf_cam_main_optical
    ph.cameras["main"].keepout_cone_deg
    ph.provenance("cam_front_optical")          # where the number comes from, and verified
    hardware.convention.world_rot_ar            # frame-convention constants

Units are metres and radians; ``ph.raw_mm`` keeps the dataset entry in millimetres to compare
with the drawings. Frame names, axes and the ``a_tf_b`` notation: :mod:`imuninn.frames`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from types import SimpleNamespace

import numpy as np

from . import _data

__all__ = ["Phone", "Camera", "Provenance", "get", "find", "list_models", "identifiers", "convention", "export"]

MM = 1e-3


@dataclass(frozen=True)
class Provenance:
    """Where a frame's numbers come from."""

    source: str
    """``definition`` (the device frame), ``drawing`` (dimensioned on Apple's drawing),
    ``role_inferred`` (position on the drawing, lens role inferred from its keep-out cone) or
    ``estimated`` (position estimated, e.g. most front cameras)."""
    verified: bool
    """Checked on a real phone. ``False`` for everything so far."""
    orientation_verified: bool | None
    """Camera frames: whether the optical axes were checked against a target (``None`` otherwise)."""
    detail: str
    """The dataset's notes: drawing reference, role basis, estimation method."""


@dataclass(frozen=True)
class Camera:
    """One camera of a model."""

    name: str
    """``main``, ``ultra_wide``, ``telephoto`` or ``front``."""
    frame: str
    """Its optical frame, e.g. ``cam_main_optical``."""
    facing: str
    """``back`` or ``front``."""
    rotation_deg: int | None
    """Sensor rotation assumed by the dataset (clockwise to upright in portrait)."""
    window_diameter_m: float | None
    keepout_cone_deg: float | None
    """Full angle of the drawing's field-of-view keep-out cone (a rough FOV bound)."""
    keepout_cone_apex_m: tuple[float, float, float] | None
    """Apex of that cone in ``device``, metres (roughly the optical centre depth)."""
    drawing_label: str | None


@dataclass(frozen=True)
class Phone:
    """Hardware constants of one model. Get one with :func:`get`."""

    slug: str
    """Dataset key, e.g. ``iphone-17-pro``."""
    name: str
    identifiers: tuple[str, ...]
    """Hardware identifiers (``DeviceInfo.model``), e.g. ``("iPhone18,1",)``. Empty when unknown."""
    raw_mm: dict = field(repr=False, compare=False)
    """The dataset entry as packaged (millimetres, drawing references)."""

    @property
    def size_m(self) -> tuple[float, float, float]:
        """Body (width, height, thickness) in metres; thickness excludes the camera bump."""
        o = self.raw_mm["outline"]
        return (o["width"] * MM, o["height"] * MM, o["thickness"] * MM)

    @property
    def camera_bump_m(self) -> float | None:
        """Height of the rear camera glass above the back plate, metres."""
        h = (self.raw_mm.get("rear_heights_from_back") or {}).get("camera_glass")
        return None if h is None else h * MM

    @property
    def dimensions_review(self) -> str:
        """Who checked this model's dimensions against Apple's drawing: ``"auto"`` (extracted
        automatically, not checked yet) or ``"human"`` (a person confirmed every value)."""
        return (self.raw_mm.get("review") or {}).get("dimensions", "auto")

    @property
    def frames(self) -> tuple[str, ...]:
        """Frame names defined for this model (``device`` first)."""
        return tuple(self.raw_mm["frames"])

    def device_tf(self, frame: str) -> np.ndarray:
        """4×4 ``device_tf_<frame>``: the frame's pose in ``device``, metres."""
        f = self._frame(frame)
        t = np.eye(4)
        t[:3, :3] = np.array(f["R"], dtype=float)
        t[:3, 3] = np.array(f["origin"], dtype=float) * MM
        return t

    def tf(self, a: str, b: str) -> np.ndarray:
        """4×4 ``a_tf_b`` between two frames of this model."""
        from .frames import inv_tf

        return inv_tf(self.device_tf(a)) @ self.device_tf(b)

    def provenance(self, frame: str) -> Provenance:
        """Where ``frame``'s numbers come from and whether they were verified."""
        f = self._frame(frame)
        o = f.get("orientation")
        detail = "; ".join(str(f[k]) for k in ("source", "role_basis", "note") if f.get(k))
        if o:
            detail = "; ".join(filter(None, [detail, f"orientation: {o.get('basis')}"]))
        return Provenance(source=f["provenance"], verified=bool(f["verified"]),
                          orientation_verified=None if o is None else bool(o.get("verified")), detail=detail)

    @property
    def cameras(self) -> dict[str, Camera]:
        """Cameras by name (``main``, ``ultra_wide``, ``telephoto``, ``front``)."""
        out = {}
        for name, c in self.raw_mm["cameras"].items():
            o = self.raw_mm["frames"][c["frame"]].get("orientation") or {}
            apex = c.get("keepout_cone_base")
            out[name] = Camera(
                name=name, frame=c["frame"], facing=c["facing"], rotation_deg=o.get("rotation_deg"),
                window_diameter_m=None if c.get("window_diameter") is None else c["window_diameter"] * MM,
                keepout_cone_deg=c.get("keepout_cone_deg"),
                keepout_cone_apex_m=None if apex is None else tuple(v * MM for v in apex),
                drawing_label=c.get("drawing_label"),
            )
        return out

    @property
    def extras(self) -> dict[str, np.ndarray]:
        """Other features (flash, rear microphone, LiDAR, ...): position in ``device``, metres."""
        return {k: np.array(v["position_in_body"], dtype=float) * MM for k, v in (self.raw_mm.get("extras") or {}).items()}

    @property
    def mass_kg(self) -> float:
        """Rough mass for simulation: the body box at 2.3 g/cm³ (glass + aluminium + battery).
        Not a published figure; replace it with the real weight when it matters."""
        w, h, t = self.size_m
        return round(w * h * t * 2300.0, 3)

    def _frame(self, frame: str) -> dict:
        try:
            return self.raw_mm["frames"][frame]
        except KeyError:
            raise KeyError(f"{self.name} has no frame {frame!r}; frames: {', '.join(self.frames)}") from None

    def to_dict(self) -> dict:
        """JSON-friendly summary in metres (what ``imuninn hardware show --json`` prints)."""
        return {
            "name": self.name, "slug": self.slug, "identifiers": list(self.identifiers),
            "size_m": list(self.size_m), "camera_bump_m": self.camera_bump_m,
            "dimensions_review": self.dimensions_review,
            "frames": {
                f: {"device_tf": self.device_tf(f).round(6).tolist(),
                    "provenance": self.provenance(f).source, "verified": self.provenance(f).verified,
                    **({"orientation_verified": self.provenance(f).orientation_verified}
                       if self.provenance(f).orientation_verified is not None else {})}
                for f in self.frames
            },
            "cameras": {k: {kk: vv for kk, vv in c.__dict__.items() if vv is not None} for k, c in self.cameras.items()},
            "extras": {k: v.round(6).tolist() for k, v in self.extras.items()},
            "frame_convention": _data.iphone_frames()["frame_convention"],
        }


@lru_cache(maxsize=None)
def _phone(slug: str) -> Phone:
    m = _data.iphone_frames()["models"][slug]
    return Phone(slug=slug, name=m["name"], identifiers=tuple(m["identifiers"]), raw_mm=m)


def find(model: str | None) -> Phone | None:
    """Like :func:`get`, but ``None`` for an unknown model."""
    slug = _data.resolve_model(model or "")
    return _phone(slug) if slug else None


def get(model: str) -> Phone:
    """Hardware constants for a model: hardware identifier (``"iPhone18,1"``), dataset key
    (``"iphone-17-pro"``) or name (``"iPhone 17 Pro"``, case and spaces ignored)."""
    ph = find(model)
    if ph is None:
        raise KeyError(f"unknown model {model!r}; see imuninn.hardware.list_models()")
    return ph


def list_models() -> list[str]:
    """Model names in the dataset, oldest first."""
    def key(slug: str):
        m = _data.iphone_frames()["models"][slug]
        return (m["drawing"].get("sheet_date") or "", m["name"])

    return [_data.iphone_frames()["models"][s]["name"] for s in sorted(_data.iphone_frames()["models"], key=key)]


def identifiers() -> dict[str, str]:
    """Hardware identifier -> model name, for the models whose identifier is known."""
    models = _data.iphone_frames()["models"]
    return {i: models[s]["name"] for i, s in _data.iphone_frames()["identifiers"].items()}


def _convention_ns() -> SimpleNamespace:
    c = _data.convention()
    ns = SimpleNamespace(**{k: np.array(v["matrix"], dtype=float) for k, v in c["rotations"].items()})
    ns.frame_convention = c["frame_convention"]
    ns.g = c["imu"]["g"]
    ns.imu_lever_arm = np.array(c["imu"]["lever_arm"]["value"], dtype=float)
    ns.quaternion_order = c["quaternion_order"]
    ns.raw = c
    return ns


convention = _convention_ns()
"""Frame-convention constants (``protocol/frames/convention.json``): ``world_rot_ar``,
``device_rot_arcam``, ``arcam_rot_optical``, ``device_rot_rear_optical``,
``device_rot_front_optical`` (3×3 arrays), ``frame_convention``, ``g``, ``imu_lever_arm``, and
``raw`` (the JSON, with every entry's ``verified`` flag)."""


def export(model: str, fmt: str, path, prefix: str = ""):
    """Write a model file for ``model``: ``fmt`` is ``"urdf"``, ``"mjcf"`` or ``"glb"`` (glb needs
    ``pip install "imuninn[models]"``); ``path`` is a file or a directory. Returns the written path.
    Details: :mod:`imuninn.models`."""
    from .models import export as _export

    return _export(get(model), fmt, path, prefix=prefix)
