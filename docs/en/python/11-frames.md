# Coordinate frames and phone hardware constants

Since 0.3 the Python package converts pose and IMU data into the frames robotics code expects, so
you no longer juggle ARKit, Core Motion and OpenCV conventions yourself. What the phone sends is
unchanged; the conversion happens once, on the PC side.

## Frames

| Name | Origin | Axes |
| --- | --- | --- |
| `world` | where the AR session started | **z up**, x = the camera's horizontal heading at session start, y left (REP 103) |
| `device` | centre of the display active area, on the front glass | x toward the right edge, y toward the top, z out of the screen (portrait; same as Core Motion) |
| `imu` | the `device` origin for now | same as `device`. Accelerometer in m/s², **flat, screen up: z = +9.81** (REP 145); gyroscope in rad/s |
| `cam_main_optical` etc. | lens window centre, on the camera cover glass | **OpenCV**: x right, y down, z forward, for the **unrotated native image**; intrinsics, pixels and depth live here |
| `magsafe` | centre of the MagSafe circle on the back | z out of the back |

Notation: `a_tf_b` is the 4×4 pose of frame b in frame a, `p_a = a_tf_b @ p_b`; `a_rot_b` is the
rotation, `a_pos_b` the translation, `a_quat_b` the quaternion `(x, y, z, w)`. Chains read left to right:

```python
world_tf_cam = pose.world_tf_device @ dev.frames.device_tf_camera("main")
```

Units are m, rad and s. MuJoCo and Isaac use `wxyz` quaternions: convert with `imuninn.frames.xyzw_to_wxyz()`.

## What you receive

```python
with imuninn.connect() as dev:
    dev.start()
    for pose in dev.iter("ar_pose"):        # imuninn.frames.Pose
        pose.world_tf_device                # 4×4, device in world
        pose.world_pos_device, pose.world_quat_device
        pose.world_tf_camera                # optical frame of the AR tracking camera (main)
        pose.raw_arkit_transform            # ARCamera.transform as sent (y up)
        pose.raw                            # the PoseSample as received
    for imu in dev.iter("imu"):             # imuninn.frames.Imu
        imu.accel, imu.gyro                 # REP 145 sign
        imu.raw_accel                       # as sent: on iOS the Core Motion sign, flat z ≈ −9.81
```

Video and depth frames stay `VideoFrame` / `DepthFrame`: their images already are in the OpenCV
optical frame. `dev.frames.device_tf_frame(frame)` gives where that frame's camera sits in the
device, picked from the frame's lens, `rotation_deg` and mirroring. Depth is registered to the main
camera, so a back-projected cloud goes to `world` like this:

```python
world_tf_cam = pose.world_tf_device @ dev.frames.device_tf_frame(depth_frame)
pts_world = pts_cam @ world_tf_cam[:3, :3].T + world_tf_cam[:3, 3]
```

## Keeping the old behaviour

Scripts written against 0.2 can ask for the protobuf messages unchanged:

```python
dev = imuninn.connect(frames="raw")          # everything as sent
dev.iter("ar_pose", frames="raw")            # just this iterator
imuninn.mcap_io.replay("run1.mcap", frames="raw")
```

`imuninn rerun` now draws a z-up world with the device and camera optical frames; `--frames raw`
restores the y-up ARKit view. `imuninn watch --raw` prints the values as sent.

## Models and camera positions

Camera and AR-origin offsets depend on the model. They come from Apple's dimensional drawings
(30 models, iPhone 12 to iPhone 18 Pro / Duo), looked up by the phone's `DeviceInfo.model`
(e.g. `iPhone18,1`).

- Unknown model: offsets are 0 and a warning is logged. Rotations are not affected.
- MCAP files converted from phone-side recordings carry no model: pass it on replay,
  `replay("rec.mcap", model="iPhone 17 Pro")`, or store it when converting:
  `imuninn convert rec.imuninn --model "iPhone 17 Pro"`.
- MCAP files recorded before 0.3 still work: without `frame_convention` metadata they read as 0 and
  convert the same way.

## Hardware constants without a phone

```python
from imuninn import hardware

hardware.list_models()                       # ["iPhone 12", ..., "iPhone 17 Pro", ...]
ph = hardware.get("iPhone 17 Pro")           # or "iPhone18,1"
ph.size_m                                    # (0.07185, 0.15001, 0.00875)
ph.frames                                    # ("device", "magsafe", "cam_main_optical", ...)
ph.device_tf("cam_main_optical")             # 4×4
ph.cameras["main"].keepout_cone_deg          # 90
ph.provenance("cam_front_optical")           # source (drawing / role inferred / estimated), verified
hardware.convention.world_rot_ar             # convention constants
```

Command line: `imuninn hardware list`, `imuninn hardware show "iPhone 17 Pro" --json`.

To look at it: the [iPhone parameter page](https://imuninn.projects.weijinqi.com/en/parameter-definition/) draws the body and every frame in 3D from the same data, for each model. `ph.dimensions_review` is `"auto"` (values read off the drawing by a program, not checked yet) or `"human"` (checked by a person).

## Exporting model files

The same data exports to formats simulators and modelling tools read directly, with every frame:

| Format | For | Content |
| --- | --- | --- |
| URDF | ROS, RViz, MoveIt, Isaac Sim | link `device` (box body, lens cylinders, estimated mass and inertia), one link per frame on a fixed joint |
| MJCF | MuJoCo | body `device` with a site per frame; no joint: attach it to your robot or add `<freejoint/>` |
| glb | Blender, three.js, Unity, Isaac (via USD) | rounded body, lenses, MagSafe ring, one named empty node per frame; glTF is y up, so the phone stands upright facing you |

```python
hardware.export("iPhone 17 Pro", "urdf", "out/")          # out/iphone_17_pro.urdf
```

```bash
imuninn hardware export "iPhone 17 Pro" --format mjcf -o out/
imuninn hardware export --all --format glb -o out/
```

Ready-made files for all 30 models can be downloaded from the [iPhone parameter page](https://imuninn.projects.weijinqi.com/en/parameter-definition/). URDF and MJCF need nothing extra; glb needs `pip install "imuninn[models]"` (trimesh). Shapes are
approximate: a box for URDF / MJCF and an estimated corner radius for glb; the mass is estimated from
the volume, so replace it when the real weight matters.

## How far to trust it

- Positions: the body, display, rear lens windows and MagSafe are dimensioned on the drawings. Which
  rear lens is the main one is inferred from its field-of-view cone. Most front-camera positions are
  estimates; on notch models they can be off by more than 1 cm.
- Camera orientations and the IMU sign are derived from Apple's documentation and **have not been
  checked against a calibration target on a real phone yet**: every constant carries
  `verified: false`. The front sensor rotation was measured only on iPhone 17 Pro (90°); older models
  assume 270° from community reports.
- Apple does not publish the IMU position, so the `imu` origin is the `device` origin. At high angular
  rates the accelerometer then picks up a lever-arm term (about 5 m/s² at 5 cm and 10 rad/s).

The constants are in `protocol/frames/` in the repository and `imuninn/data/` in the installed package.
