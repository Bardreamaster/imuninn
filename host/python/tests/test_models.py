"""Model export (imuninn.models): URDF / MJCF from the standard library, glb with trimesh."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from imuninn import hardware, models
from imuninn.frames import quat_to_rot, wxyz_to_xyzw


def _floats(s: str) -> np.ndarray:
    return np.array([float(x) for x in s.split()])


@pytest.mark.parametrize("name", hardware.list_models())
def test_urdf_joints_match_frames(name):
    ph = hardware.get(name)
    root = ET.fromstring(models.to_urdf(ph).split("\n", 2)[2])   # skip the XML declaration and comment
    links = {link.get("name") for link in root.findall("link")}
    assert {"device", "imu", *ph.frames} <= links
    for j in root.findall("joint"):
        child = j.find("child").get("link")
        o = j.find("origin")
        want = np.eye(4) if child == "imu" else ph.device_tf(child)
        assert np.allclose(_floats(o.get("xyz")), want[:3, 3], atol=1e-9), child
        assert np.allclose(models.rpy_to_rot(_floats(o.get("rpy"))), want[:3, :3], atol=1e-8), child
    mass = float(root.find("link/inertial/mass").get("value"))
    assert 0.1 < mass < 0.4


def test_mjcf_sites_match_frames():
    ph = hardware.get("iPhone 17 Pro")
    root = ET.fromstring(models.to_mjcf(ph).split("\n", 1)[1])
    sites = {s.get("name"): s for s in root.iter("site")}
    for f in ph.frames[1:]:
        s = sites[f]
        want = ph.device_tf(f)
        assert np.allclose(_floats(s.get("pos")), want[:3, 3], atol=1e-9)
        assert np.allclose(quat_to_rot(wxyz_to_xyzw(_floats(s.get("quat")))), want[:3, :3], atol=1e-8)


def test_mjcf_loads_in_mujoco(tmp_path):
    mujoco = pytest.importorskip("mujoco")
    p = models.export("iPhone 17 Pro", "mjcf", tmp_path)
    m = mujoco.MjModel.from_xml_path(str(p))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    sid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, "cam_main_optical")
    assert np.allclose(d.site_xpos[sid], hardware.get("iPhone 17 Pro").device_tf("cam_main_optical")[:3, 3])


def test_glb_nodes(tmp_path):
    trimesh = pytest.importorskip("trimesh")
    ph = hardware.get("iPhone 17 Pro")
    p = models.export(ph, "glb", tmp_path / "phone.glb")
    sc = trimesh.load(str(p))
    for f in ph.frames[1:]:
        assert np.allclose(sc.graph.get(f)[0], ph.device_tf(f), atol=1e-6), f
    lo, hi = sc.bounds
    assert hi[1] - lo[1] == pytest.approx(ph.size_m[1], abs=1e-4)


def test_export_paths(tmp_path):
    p = hardware.export("iPhone18,1", "urdf", tmp_path)
    assert p.name == "iphone_17_pro.urdf" and p.exists()
    q = models.export("iPhone 12", "mjcf", tmp_path / "sub" / "x.xml", prefix="phone_")
    assert q.name == "x.xml" and 'name="phone_device"' in q.read_text()
    with pytest.raises(ValueError):
        models.export("iPhone 12", "stl", tmp_path)


def test_export_bundle(tmp_path):
    manifest = models.export_bundle(tmp_path, formats=("urdf", "mjcf"))   # no trimesh needed
    assert manifest == json.loads((tmp_path / "manifest.json").read_text())
    assert len(manifest["models"]) == len(hardware.list_models())
    entry = manifest["models"]["iphone-17-pro"]
    assert entry["name"] == "iPhone 17 Pro"
    for fmt in ("urdf", "mjcf"):
        f = tmp_path / entry["files"][fmt]["path"]
        assert f.stat().st_size == entry["files"][fmt]["bytes"]
    assert manifest["data_sha256"] == models.data_fingerprint()


SITE_MODELS = Path(__file__).resolve().parents[3] / "site" / "public" / "parameter-definition" / "models"
REGENERATE = "run: imuninn hardware export --all --format all -o site/public/parameter-definition/models"


@pytest.mark.skipif(not SITE_MODELS.is_dir(), reason="not a repository checkout")
def test_site_model_files_are_current():
    """The model files the site serves must match the frame table (they are committed, not built)."""
    manifest = json.loads((SITE_MODELS / "manifest.json").read_text())
    assert manifest["data_sha256"] == models.data_fingerprint(), REGENERATE
    slugs = {hardware.get(n).slug for n in hardware.list_models()}
    assert set(manifest["models"]) == slugs, REGENERATE
    for slug in slugs:
        ph = hardware.get(slug)
        files = manifest["models"][slug]["files"]
        assert set(files) == set(models.FORMATS), REGENERATE
        for fmt, f in files.items():
            assert (SITE_MODELS / f["path"]).stat().st_size == f["bytes"], REGENERATE
        assert (SITE_MODELS / files["urdf"]["path"]).read_text() == models.to_urdf(ph), REGENERATE
        assert (SITE_MODELS / files["mjcf"]["path"]).read_text() == models.to_mjcf(ph), REGENERATE
