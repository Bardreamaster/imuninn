# Rerun 可视化

```bash
pip install "imuninn[rerun]"
imuninn rerun --start                    # 连第一台手机，启动 Rerun Viewer，开始采集
imuninn rerun iPhone --depth --points    # 开深度，PC 端反投影成点云
imuninn rerun 手机A 手机B                 # 多台手机同一个 Viewer
imuninn rerun --mcap run1.mcap           # 回放录制
imuninn rerun --save run1.rrd iPhone     # 不开窗口，直接写 .rrd
```

## Viewer 里的布局

每台手机一棵子树（`<dev>` 是设备名），用[统一坐标系](11-frames.md)：`world` z 朝上。

| 实体 | 内容 |
| --- | --- |
| `world/<dev>` | 机身位姿 `world_tf_device` |
| `world/<dev>/trajectory` | 机身原点的轨迹 |
| `world/<dev>/cam` + `/video` | 镜头光学系 `device_tf_cam_*_optical` + 针孔相机 + 图像 |
| `world/<dev>/depth/image`、`/confidence` | 主摄光学系下的深度（米）与置信度 |
| `world/<dev>/depth_points` | 深度反投影点云（`--points`，用 RGB 着色） |
| `plots/<dev>/imu/*`、`pose/tracking`、`health/*` | IMU 曲线、追踪状态、热状态 / 电量 / 帧率 |
| `events/<dev>` | 追踪 / 热状态 / 低电量变化、丢帧、配置变更 |

时间轴：`pc`（墙钟，多台手机共用）和 `device`（手机单调时钟）。

`--frames raw` 回到 0.3 之前的画法：y 朝上的 ARKit 世界，`world/<dev>` 是 ARKit 相机，点云在 `world/<dev>/points`。回放没有 `/device` 的 MCAP 时用 `--model "iPhone 17 Pro"` 指定机型，否则镜头偏移取 0。

## 选项

| 选项 | 作用 |
| --- | --- |
| `--video decode`（默认） | 本机 PyAV 解码再送图像，稳定 60 fps |
| `--video stream` | 把 H.264 直接交给 Viewer 解码；原生 Viewer 要 PATH 上有 `ffmpeg`，1920×1440@60 会卡顿 |
| `--every N` | 每 N 帧解一帧，省 CPU |
| `--scale 0.5` | 解码后缩放再送 Viewer（默认 0.5，内参同步缩放） |
| `--buffer-ms 150` | 播放缓冲：按设备时间顺序延迟 N 毫秒释放，抚平 Wi‑Fi 突发到达 |
| `--points` / `--point-stride` / `--points-hz` | 点云、点云抽样步长、点云与置信度图的频率上限（默认 10 Hz） |
| `--no-trajectory` / `--no-blueprint` | 不画轨迹 / 不用预设布局 |
| `--port` | 用自己的 Viewer 端口（默认 9876） |
| `--seconds N` | 跑 N 秒后退出 |

全部选项见 [CLI 参考](07-cli.md#imuninn-rerun)。

## 浏览一整个文件夹的录制

```bash
imuninn browse ~/recordings        # 扫描、预估、确认后转换，再在 Viewer 里列出全部录制
imuninn to-rrd ~/recordings        # 只转换，不开 Viewer
```

Viewer 读不懂 imuninn 的 protobuf 消息，所以每个 `.mcap` 先经过与 `imuninn rerun --mcap` 相同的处理，存成一个 `.rrd`。`browse` 再用 `rerun server -d` 把这些 `.rrd` 作为一个数据集（dataset）提供给 Viewer：窗口里是一张录制列表，点哪条才加载哪条。

- **扫描**：递归查找输入文件夹下的 `.mcap`，跳过以 `_` 或 `.` 开头的子文件夹（输出就放在这样的文件夹里）。
- **确认**：`browse` 先打印找到多少个文件、多少已是最新、预计新增多少空间和时间、输出放在哪里，回车确认后才转换。`-y` 跳过确认；不在终端里运行时必须加 `-y`。`to-rrd` 不询问。
- **输出**：默认 `<输入文件夹>/_rerun/`，一个平铺的文件夹（数据集服务只读一层）。`run1/top.mcap` 存为 `run1__top.rrd`，列表里显示为 `run1/top`。`-o` 指定别的位置。
- **增量**：`.rrd` 比 `.mcap` 新就跳过，`--force` 全部重转。中断留下的 `*.rrd.part` 会在下次运行时删除。
- **画质**：默认 `--video stream`，原样保存录制时的 H.264，体积约等于 MCAP，几秒转完；原生 Viewer 播放时要 PATH 上有 `ffmpeg`。`--video decode` 存解码后的 JPEG 帧（`--scale` 默认 1 即原尺寸），体积约为 MCAP 的几十倍，转换也慢得多；`--video off` 不存视频。非默认设置输出到 `_rerun-decode`、`_rerun-novideo` 等独立文件夹，不会和默认输出混在一起。
- **布局**：装了 `rerun-sdk[catalog]`（约 200 MB，含 datafusion / pandas）时，`browse` 会给数据集登记 imuninn 的布局，并直接打开录制列表；没装时 Viewer 停在服务器的数据集列表，点数据集名进入，录制用 Rerun 的自动布局。
- 关掉 Viewer 窗口即结束；`--no-viewer` 只运行数据集服务，并打印可以用 `rerun <地址>` 打开的地址。
