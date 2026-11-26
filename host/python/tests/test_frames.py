"""Unified frames (imuninn.frames) and hardware constants (imuninn.hardware): offline checks."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from imuninn import frames as fr
from imuninn import hardware
from imuninn.proto import imuninn_pb2 as pb

REPO = Path(__file__).resolve().parents[3]


def _is_rotation(m) -> bool:
    m = np.asarray(m, float)
    return np.allclose(m @ m.T, np.eye(3)) and math.isclose(np.linalg.det(m), 1.0)


def _pose(pos=(0, 0, 0), quat=(0, 0, 0, 1)) -> pb.PoseSample:
    s = pb.PoseSample()
    s.position.CopyFrom(pb.Vec3(x=pos[0], y=pos[1], z=pos[2]))
    s.orientation.CopyFrom(pb.Quat(x=quat[0], y=quat[1], z=quat[2], w=quat[3]))
    s.tracking = pb.TRACKING_STATE_NORMAL
    return s


# -- constants ----------------------------------------------------------------


def test_convention_matrices_are_rotations():
    for name, r in hardware.convention.raw["rotations"].items():
        assert _is_rotation(r["matrix"]), name
        assert r["verified"] is False   # nothing checked on a phone yet (convention doc section 5)


def test_rear_optical_is_arcam_times_flip():
    assert np.allclose(fr.DEVICE_ROT_ARCAM @ fr.ARCAM_ROT_OPTICAL, fr.DEVICE_ROT_REAR_OPTICAL)


def test_optical_rule_matches_tabulated_matrices():
    assert np.allclose(fr.device_rot_optical("main", 90), fr.DEVICE_ROT_REAR_OPTICAL)
    assert np.allclose(fr.device_rot_optical("front", 90), fr.DEVICE_ROT_FRONT_OPTICAL)
    for cam in ("main", "front"):
        for rot in (0, 90, 180, 270):
            assert _is_rotation(fr.device_rot_optical(cam, rot)), (cam, rot)
    with pytest.raises(ValueError):
        fr.device_rot_optical("main", 45)


def test_rotation_deg_upright_check():
    """Rotating the native image clockwise by rotation_deg must make it upright in portrait:
    image x -> device +X for the back camera (looking through the phone), -X for the front."""
    for cam, want_x in (("main", [1, 0, 0]), ("front", [-1, 0, 0])):
        for rot in (0, 90, 180, 270):
            r = fr.device_rot_optical(cam, rot)
            x, y = r[:, 0], r[:, 1]
            # clockwise rotation by rot: native x -> upright direction
            k = rot // 90
            up_x = [x, -y, -x, y][k]   # the native axis that ends up pointing right after the rotation
            assert np.allclose(up_x, want_x), (cam, rot)


def test_front_and_back_z_are_opposite():
    assert np.allclose(fr.device_rot_optical("main")[:, 2], [0, 0, -1])
    assert np.allclose(fr.device_rot_optical("front")[:, 2], [0, 0, 1])
    ph = hardware.get("iPhone 17 Pro")
    zb = ph.device_tf("cam_main_optical")[:3, 2]
    zf = ph.device_tf("cam_front_optical")[:3, 2]
    assert np.allclose(zb, -zf)


def test_mirrored_is_a_reflection():
    m = fr.device_rot_optical("front", 90, mirrored=True)
    assert math.isclose(np.linalg.det(m), -1.0)
    with pytest.raises(ValueError):
        fr.rot_to_quat(m)


# -- transform helpers ----------------------------------------------------------


def test_quaternion_roundtrip_and_order():
    rng = np.random.default_rng(1)
    for _ in range(50):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        q = q if q[3] >= 0 else -q
        r = fr.quat_to_rot(q)
        assert _is_rotation(r)
        assert np.allclose(fr.rot_to_quat(r), q)
    assert np.allclose(fr.xyzw_to_wxyz([1, 2, 3, 4]), [4, 1, 2, 3])
    assert np.allclose(fr.wxyz_to_xyzw([4, 1, 2, 3]), [1, 2, 3, 4])


def test_compose_and_inverse():
    rng = np.random.default_rng(2)
    a_tf_b = fr.tf_from_pos_quat(rng.normal(size=3), rng.normal(size=4))
    b_tf_c = fr.tf_from_pos_quat(rng.normal(size=3), rng.normal(size=4))
    a_tf_c = a_tf_b @ b_tf_c
    assert np.allclose(fr.inv_tf(a_tf_b) @ a_tf_c, b_tf_c)
    assert np.allclose(fr.inv_tf(fr.inv_tf(a_tf_c)), a_tf_c)
    assert np.allclose(a_tf_c @ fr.inv_tf(a_tf_c), np.eye(4))
    p, q = fr.pos_quat_from_tf(a_tf_c)
    assert np.allclose(fr.tf_from_pos_quat(p, q), a_tf_c)


# -- IMU ----------------------------------------------------------------------


def test_flat_iphone_reads_plus_g():
    s = pb.ImuSample()
    s.accel.CopyFrom(pb.Vec3(x=0.0, y=0.0, z=-9.80665))   # what Core Motion reports flat, screen up
    s.gyro.CopyFrom(pb.Vec3(x=0.0, y=0.0, z=0.5))
    imu = fr.FrameConverter(model="iPhone18,1", platform=pb.PLATFORM_IOS).imu(s)
    assert imu.accel[2] == pytest.approx(9.80665)
    assert imu.gyro[2] == pytest.approx(0.5)
    assert imu.raw_accel[2] == pytest.approx(-9.80665)
    assert not np.signbit(imu.accel[0])   # no -0.0 in the output


def test_android_accel_kept():
    s = pb.ImuSample()
    s.accel.z = 9.81
    a, _ = fr.imu_to_ros(s, pb.PLATFORM_ANDROID)
    assert a[2] == pytest.approx(9.81)


# -- AR pose --------------------------------------------------------------------


def test_identity_arkit_pose():
    """ARCamera.transform = I: phone in landscape (bottom on the right), back camera looking along
    AR -z = world +x. So device +X points up, device +Y points world +y (left), screen faces -x."""
    conv = fr.FrameConverter(model="iPhone18,1")
    u = conv.pose(_pose())
    r = u.world_rot_device
    assert np.allclose(r[:, 0], [0, 0, 1])
    assert np.allclose(r[:, 1], [0, 1, 0])
    assert np.allclose(r[:, 2], [-1, 0, 0])
    # the AR camera (main lens) sits at the world origin
    p_main = hardware.get("iPhone18,1").device_tf("cam_main_optical")[:3, 3]
    assert np.allclose(u.world_tf_device @ np.append(p_main, 1), [0, 0, 0, 1])
    # the optical frame looks along world +x, image y (down) is world -z
    assert np.allclose(u.world_tf_camera[:3, 2], [1, 0, 0])
    assert np.allclose(u.world_tf_camera[:3, 1], [0, 0, -1])
    assert np.allclose(u.world_tf_camera[:3, 3], [0, 0, 0])
    assert np.allclose(u.raw_arkit_transform, np.eye(4))


def test_portrait_arkit_pose_is_upright_device():
    """Phone held in portrait, back camera facing the session's start heading: ARKit camera rotated
    -90 deg about its z (= the AR world z). Then device +Y must point up in world (z)."""
    a = -math.pi / 2
    q = (0, 0, math.sin(a / 2), math.cos(a / 2))
    u = fr.FrameConverter(model="iPhone 17 Pro").pose(_pose((1.0, 2.0, 3.0), q))
    r = u.world_rot_device
    assert np.allclose(r[:, 1], [0, 0, 1], atol=1e-9)          # device top up
    assert np.allclose(r[:, 2], [-1, 0, 0], atol=1e-9)         # screen faces back toward -x
    assert np.allclose(r[:, 0], [0, -1, 0], atol=1e-9)         # device right = world -y (right of FLU)
    # translation follows world_rot_ar: AR (1, 2, 3) -> world (-3, -1, 2), at the camera
    assert np.allclose(u.world_tf_camera[:3, 3], [-3, -1, 2])
    assert _is_rotation(u.world_rot_device)


def test_pose_and_imu_agree_on_up():
    """A phone at rest in portrait: Core Motion's gravity is (0, -1, 0) g, so iOS sends accel
    (0, -9.81, 0). Converted to specific force and rotated by the portrait pose's world_rot_device
    it must point up in world (+z): the pose and IMU conversions share one device frame."""
    a = -math.pi / 2
    conv = fr.FrameConverter(model="iPhone18,1", platform=pb.PLATFORM_IOS)
    pose = conv.pose(_pose(quat=(0, 0, math.sin(a / 2), math.cos(a / 2))))
    s = pb.ImuSample()
    s.accel.y = -fr.G
    f_world = pose.world_rot_device @ conv.imu(s).accel
    assert np.allclose(f_world, [0, 0, fr.G], atol=1e-9)


def test_unknown_model_falls_back_to_zero_offset(caplog):
    conv = fr.FrameConverter(model="iPhone99,9")
    assert conv.hardware is None
    assert "no frame data" in caplog.text
    u = conv.pose(_pose())
    assert np.allclose(u.world_pos_device, 0)


def test_from_device_info():
    info = pb.DeviceInfo(model="iPhone18,1", platform=pb.PLATFORM_IOS)
    conv = fr.FrameConverter.from_device_info(info)
    assert conv.model_name == "iPhone 17 Pro" and conv.ar_camera == "main"
    vf = pb.VideoFrame(rotation_deg=90)
    t = conv.device_tf_frame(vf)
    assert np.allclose(t, hardware.get("iPhone18,1").device_tf("cam_main_optical"))


# -- hardware -------------------------------------------------------------------


def test_hardware_lookup():
    names = hardware.list_models()
    assert len(names) == 30 and "iPhone 17 Pro" in names
    a, b, c = hardware.get("iPhone18,1"), hardware.get("iPhone 17 Pro"), hardware.get("iphone-17-pro")
    assert a is b is c
    assert hardware.get("iPhone SE (2nd generation)").slug == "iphone-se-3rd-generation"
    assert hardware.find("Nokia 3310") is None
    with pytest.raises(KeyError):
        hardware.get("Nokia 3310")
    assert hardware.identifiers()["iPhone18,1"] == "iPhone 17 Pro"


def test_hardware_values_in_metres():
    ph = hardware.get("iPhone 17 Pro")
    assert ph.size_m == pytest.approx((0.07185, 0.15001, 0.00875))
    assert ph.frames[0] == "device"
    assert np.allclose(ph.device_tf("device"), np.eye(4))
    t = ph.device_tf("cam_main_optical")
    assert np.allclose(t[:3, 3], [0.021555, 0.041395, -0.01318])
    assert _is_rotation(t[:3, :3])
    assert np.allclose(ph.tf("cam_main_optical", "cam_main_optical"), np.eye(4))
    assert ph.cameras["main"].keepout_cone_deg == 90
    assert ph.provenance("cam_front_optical").source == "estimated"
    assert ph.provenance("cam_main_optical").orientation_verified is False
    assert ph.provenance("device").verified is True
    with pytest.raises(KeyError):
        ph.device_tf("cam_periscope_optical")
    json.dumps(ph.to_dict())


def test_dimensions_review_status():
    assert {hardware.get(n).dimensions_review for n in hardware.list_models()} <= {"auto", "human"}
    assert hardware.get("iPhone 17 Pro").to_dict()["dimensions_review"] in ("auto", "human")


def test_every_model_has_proper_frames():
    for name in hardware.list_models():
        ph = hardware.get(name)
        assert "cam_main_optical" in ph.frames, name
        for f in ph.frames:
            assert _is_rotation(ph.device_tf(f)[:3, :3]), (name, f)


@pytest.mark.skipif(not (REPO / "protocol" / "frames").is_dir(), reason="not a repository checkout")
def test_packaged_data_matches_protocol_frames():
    pkg = Path(fr.__file__).parent / "data"
    for f in ("convention.json", "iphone-frames.json"):
        assert (pkg / f).read_bytes() == (REPO / "protocol" / "frames" / f).read_bytes(), \
            f"{f}: run tools/gen-frames.py (or tools/gen-proto.sh) to refresh imuninn/data"
    # review.json is the hand-edited source of each model's review entry
    review = json.loads((REPO / "protocol" / "frames" / "review.json").read_text())
    models = json.loads((pkg / "iphone-frames.json").read_text())["models"]
    for slug, m in models.items():
        want = review["models"].get(slug, {}).get("dimensions", review["default"])
        assert m["review"]["dimensions"] == want, f"{slug}: run tools/gen-frames.py after editing review.json"


# -- entry points ---------------------------------------------------------------


def test_device_delivers_unified_and_raw():
    from imuninn.session import Device

    dev = Device("127.0.0.1", 1, frames="unified")
    dev._client.info = pb.DeviceInfo(model="iPhone18,1", platform=pb.PLATFORM_IOS)
    got_u, got_r, got_all = [], [], []
    dev.on("imu", got_u.append)
    dev.on("imu", got_r.append, frames="raw")
    dev.on("*", lambda s, x: got_all.append(x))
    msg = pb.DataMessage(imu=pb.ImuSample(header=pb.Header(stream_id="imu"), accel=pb.Vec3(z=-9.8)))
    dev._on_data(msg)
    assert isinstance(got_u[0], fr.Imu) and got_u[0].accel[2] == pytest.approx(9.8)
    assert isinstance(got_r[0], pb.ImuSample)
    assert got_all[0] is got_u[0]   # converted once, shared
    with pytest.raises(ValueError):
        Device("127.0.0.1", 1, frames="ros")


def test_mcap_metadata_and_replay(tmp_path):
    pytest.importorskip("mcap_protobuf")
    from imuninn.mcap_io import McapRecorder, read_frame_convention, read_metadata, replay

    path = tmp_path / "f.mcap"
    with McapRecorder(path, device=pb.DeviceInfo(model="iPhone18,1", platform=pb.PLATFORM_IOS)) as rec:
        rec.write(pb.DataMessage(pose=_pose()), log_time_ns=1)
        rec.write(pb.DataMessage(imu=pb.ImuSample(header=pb.Header(stream_id="imu"), accel=pb.Vec3(z=-9.8))), log_time_ns=2)
    assert read_frame_convention(path) == fr.FRAME_CONVENTION
    assert read_metadata(path)["device_model"] == "iPhone18,1"
    samples = [s for _, s in replay(path)]
    assert isinstance(samples[0], fr.Pose) and isinstance(samples[1], fr.Imu)
    assert samples[1].accel[2] == pytest.approx(9.8)
    assert samples[0].world_tf_device[:3, 3] == pytest.approx(
        -fr.tf_rot(samples[0].world_tf_device) @ hardware.get("iPhone18,1").device_tf("cam_main_optical")[:3, 3])
    raw = [s for _, s in replay(path, frames="raw")]
    assert isinstance(raw[0], pb.PoseSample)


def test_old_mcap_reads_as_convention_0(tmp_path):
    pytest.importorskip("mcap_protobuf")
    from mcap_protobuf.writer import Writer

    from imuninn.mcap_io import read_frame_convention, replay

    path = tmp_path / "old.mcap"
    with open(path, "wb") as f:   # what 0.2 wrote: no metadata, no /device
        w = Writer(f)
        w.write_message("/imu", pb.ImuSample(header=pb.Header(stream_id="imu"), accel=pb.Vec3(z=-9.8)), log_time=1, publish_time=1)
        w.finish()
    assert read_frame_convention(path) == 0
    (_, s), = list(replay(path, model="iPhone 17 Pro"))
    assert s.accel[2] == pytest.approx(9.8)


def test_protocol_v7_fields():
    """DeviceInfo.frame_convention / ar_capture_device_type and VideoFrame.camera / mirrored."""
    info = pb.DeviceInfo(model="iPhone18,1", platform=pb.PLATFORM_IOS, frame_convention=1,
                         ar_capture_device_type="AVCaptureDeviceTypeBuiltInUltraWideCamera")
    conv = fr.FrameConverter.from_device_info(info)
    assert conv.ar_camera == "ultra_wide" and conv.frame_convention == 1
    ph = hardware.get("iPhone18,1")
    u = conv.pose(_pose())
    p_uw = ph.device_tf("cam_ultra_wide_optical")[:3, 3]
    assert np.allclose(u.world_tf_device @ np.append(p_uw, 1), [0, 0, 0, 1])   # AR origin at that lens

    front = pb.VideoFrame(rotation_deg=90, camera="front")
    assert conv.frame_camera(front) == "front"
    assert np.allclose(conv.device_tf_frame(front), ph.device_tf("cam_front_optical"))
    mirrored = pb.VideoFrame(rotation_deg=90, camera="front", mirrored=True)
    assert math.isclose(np.linalg.det(conv.device_tf_frame(mirrored)[:3, :3]), -1.0)
    assert conv.frame_camera(pb.VideoFrame(camera="back_telephoto")) == "telephoto"
    assert conv.frame_camera(pb.DepthFrame(camera="back_wide")) == "main"
    assert conv.frame_camera(pb.DepthFrame()) == "ultra_wide"   # unreported: the AR camera


def test_newer_phone_convention_warns(caplog):
    fr.FrameConverter.from_device_info(pb.DeviceInfo(model="iPhone18,1", frame_convention=fr.FRAME_CONVENTION + 1))
    assert "update imuninn" in caplog.text
