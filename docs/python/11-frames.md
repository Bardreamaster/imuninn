# 坐标系与手机硬件常量

从 0.3 起，Python 包把位姿和 IMU 统一换算成机器人领域常用的坐标系，使用者不用再自己处理 ARKit、Core Motion 和 OpenCV 之间的差别。手机发的数据没变，换算只在 PC 端入口做一次。

## 坐标系

| 名字 | 原点 | 轴向 |
| --- | --- | --- |
| `world` | AR 会话开始处 | **z 朝上**，x 为会话开始时相机的水平朝向，y 朝左（REP 103） |
| `device` | 屏幕显示区中心，在前盖玻璃表面 | x 指向右边框，y 指向顶部，z 垂直屏幕朝外（竖持，与 Core Motion 相同） |
| `imu` | 暂取 `device` 原点 | 同 `device`。加速度 m/s²，**静止平放屏幕朝上 z = +9.81**（REP 145）；角速度 rad/s |
| `cam_main_optical` 等 | 镜头窗口中心，在摄像头盖玻璃表面 | **OpenCV**：x 右、y 下、z 朝拍摄方向，以**未旋转的原生图像**为准，内参、像素、深度都在这个系 |
| `magsafe` | 背面 MagSafe 圆心 | z 垂直背板朝外 |

记法：`a_tf_b` 是坐标系 b 在 a 中的 4×4 位姿，`p_a = a_tf_b @ p_b`；`a_rot_b` 是旋转，`a_pos_b` 是平移，`a_quat_b` 是四元数 `(x, y, z, w)`。所以可以直接链式相乘：

```python
world_tf_cam = pose.world_tf_device @ dev.frames.device_tf_camera("main")
```

单位一律 m、rad、s。MuJoCo 和 Isaac 用 `wxyz` 四元数，用 `imuninn.frames.xyzw_to_wxyz()` 转。

## 收到的是什么

```python
with imuninn.connect() as dev:
    dev.start()
    for pose in dev.iter("ar_pose"):        # imuninn.frames.Pose
        pose.world_tf_device                # 4×4，world 中的 device
        pose.world_pos_device, pose.world_quat_device
        pose.world_tf_camera                # AR 追踪用的镜头（主摄）的光学系
        pose.raw_arkit_transform            # 手机发来的 ARCamera.transform（y 朝上），原样
        pose.raw                            # 原始 PoseSample
    for imu in dev.iter("imu"):             # imuninn.frames.Imu
        imu.accel, imu.gyro                 # REP 145 符号
        imu.raw_accel                       # 原样：iOS 是 Core Motion 符号，平放 z ≈ −9.81
```

视频和深度帧仍是原来的 `VideoFrame` / `DepthFrame`：图像本来就在 OpenCV 光学系里。它们在机身里的位置用 `dev.frames.device_tf_frame(frame)` 取，这个函数按帧的镜头、`rotation_deg` 和是否镜像选矩阵。深度和主摄对齐，所以深度点云可以这样变到 `world`：

```python
from imuninn.depth import decode, to_metres

d = to_metres(decode(depth_frame, upright=False)[0])     # 原生方向
# ... 用 depth_frame.intrinsics 反投影得到 pts_cam (N×3)
world_tf_cam = pose.world_tf_device @ dev.frames.device_tf_frame(depth_frame)
pts_world = pts_cam @ world_tf_cam[:3, :3].T + world_tf_cam[:3, 3]
```

## 保持旧行为

依赖 0.2 输出的脚本，在连接时加 `frames="raw"`，拿到的就是原来的 protobuf 消息：

```python
dev = imuninn.connect(frames="raw")          # 全部原样
dev.iter("ar_pose", frames="raw")            # 只这一处原样
imuninn.mcap_io.replay("run1.mcap", frames="raw")
```

`imuninn rerun` 默认画 z 朝上的 world、机身和镜头的光学系，`--frames raw` 回到原来的 y 朝上画法。`imuninn watch --raw` 打印原样数值。

## 机型和镜头位置

相机和 AR 原点的偏移按机型取，数据来自 Apple 公开的外观尺寸图（30 款，iPhone 12 到 iPhone 18 Pro / Duo）。机型用手机报告的 `DeviceInfo.model`（如 `iPhone18,1`）查。

- 查不到机型时偏移取 0，并在日志里警告。旋转不受影响。
- 从手机端录制转换出来的 MCAP 没有机型，回放时传 `model=`：`replay("rec.mcap", model="iPhone 17 Pro")`，或转换时就写进去：`imuninn convert rec.imuninn --model "iPhone 17 Pro"`。
- 0.3 之前录的 MCAP 照常能读：没有 `frame_convention` 元数据就按 0 处理，换算方法相同。

## 不连手机读硬件常量

```python
from imuninn import hardware

hardware.list_models()                       # ["iPhone 12", ..., "iPhone 17 Pro", ...]
ph = hardware.get("iPhone 17 Pro")           # 也可以用 "iPhone18,1"
ph.size_m                                    # (0.07185, 0.15001, 0.00875)
ph.frames                                    # ("device", "magsafe", "cam_main_optical", ...)
ph.device_tf("cam_main_optical")             # 4×4
ph.cameras["main"].keepout_cone_deg          # 90
ph.provenance("cam_front_optical")           # 来源（图纸标注 / 角色推断 / 估计）和 verified
hardware.convention.world_rot_ar             # 换算常数
```

命令行：`imuninn hardware list`、`imuninn hardware show "iPhone 17 Pro" --json`。

想直接看：[iPhone 参数页](https://imuninn.projects.weijinqi.com/parameter-definition/)用同一份数据把机身和各坐标系画成 3D，可以切换机型。`ph.dimensions_review` 是 `"auto"`（数值由程序从图纸读出，还没人核对）或 `"human"`（已人工核验）。

## 导出模型文件

同一份数据可以导出成仿真和建模软件能直接读的格式，每个坐标系都在里面：

| 格式 | 给谁用 | 内容 |
| --- | --- | --- |
| URDF | ROS、RViz、MoveIt、Isaac Sim | link `device`（长方体机身、镜头圆柱、估算的质量和惯量），每个坐标系一个 link，用 fixed joint 连到 `device` |
| MJCF | MuJoCo | body `device`，每个坐标系一个 site；没有关节，挂到你的机器人上，或加 `<freejoint/>` |
| glb | Blender、three.js、Unity、Isaac（转 USD） | 圆角机身、镜头、MagSafe 圆环，每个坐标系一个具名空节点；glTF 是 y 朝上，打开时手机竖立、屏幕朝你 |

```python
hardware.export("iPhone 17 Pro", "urdf", "out/")          # out/iphone_17_pro.urdf
```

```bash
imuninn hardware export "iPhone 17 Pro" --format mjcf -o out/
imuninn hardware export --all --format glb -o out/
```

30 个机型导出好的文件可以在 [iPhone 参数页](https://imuninn.projects.weijinqi.com/parameter-definition/)直接下载。URDF 和 MJCF 不需要额外依赖；glb 需要 `pip install "imuninn[models]"`（trimesh）。外形是近似的：URDF / MJCF 用长方体，glb 的圆角半径是估计值；质量按体积估算，真实重量要紧时请替换。

## 可信度

- 位置：机身、显示区、后摄窗口、MagSafe 是图纸直接标的。后摄哪颗是主摄是按视场锥角推断的。前摄位置多数是估计，刘海机型可能差 1 cm 以上。
- 相机朝向和 IMU 符号是由 Apple 文档推出来的，**还没有在真机上用标定板核对**，常数文件里每条都标着 `verified: false`。前摄的传感器旋转只在 iPhone 17 Pro 上测过（90°），旧机型按社区经验取 270°。
- Apple 不公布 IMU 的位置，`imu` 原点暂取 `device` 原点。角速度大时，加速度会多出杆臂项（5 cm、10 rad/s 约 5 m/s²）。

常数在仓库的 `protocol/frames/`，装好的包里在 `imuninn/data/`。
