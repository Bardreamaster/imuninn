# iMuninn 协议

[English](README.en.md)

`imuninn.proto` 是手机端、PC 端、所有语言绑定的唯一真相源。改协议时三端在同一个 commit 中同步更新，并 bump `VERSION`。

消息字段参考（生成）：`docs/protocol/messages.md`。

## 版本

版本分两层：

| 层 | 在哪 | 什么时候变 |
| --- | --- | --- |
| 协议版本（整数，现在是 7，文档里写作 v7） | `VERSION` 文件；每条消息头的 `Header.protocol_version`，以及 `Hello`、`Welcome`、`DeviceInfo` | 兼容的改动，每次加 1 |
| 包名（`imuninn.v1`） | `imuninn.proto` 的 `package` | 不兼容的改动，升到 `imuninn.v2` |

规则：

1. **只加可选字段、加消息、加枚举值，整数加 1。** 旧客户端会忽略不认识的字段，新客户端读旧数据时新字段是默认值（0、空串、`false`），所以新字段的默认值必须表示“没有报告”。
2. **删字段、改字段号或类型、改已有字段的含义，升包名到 `v2`。** 在 `v1` 里这些都不做：不再用的字段标 `reserved`，字段号不复用；含义要变就加一个新字段，旧字段保持原样。
3. **客户端按“版本号 ≥ N 才用某功能”判断，不要求两边相等。** 版本不同是正常情况（App 和 PC 端各自升级）。Python 包和 Web 查看器在版本不同时只打一行 `protocol mismatch` 日志，照常工作。

协议版本和 App、Python 包的版本号（如 0.2.0）互相独立。坐标系约定另有自己的整数 `frame_convention`（见[坐标系](#坐标系)），改坐标系定义不一定要改协议。

各版本加了什么（N 的取值）：

| 版本 | 新增 |
| --- | --- |
| v3 | `health` 流（`DeviceHealth`） |
| v4 | `DeviceConfig.session_params` |
| v5 | `Hello.data_transport`，数据流走 WebSocket（浏览器） |
| v6 | `audio` 流（`AudioChunk`） |
| v7 | 坐标系元数据：`DeviceInfo.frame_convention` / `ar_capture_device_type`，`VideoFrame` / `DepthFrame` 的 `camera` / `mirrored` |

## 通道

| 通道 | 传输 | 消息 | 丢包策略 |
| --- | --- | --- | --- |
| 控制 | WebSocket | `ControlMessage` | 可靠 |
| IMU / 位姿 / 健康 | UDP（手机 → 每个客户端的端口），每包一条 `DataMessage` | `ImuSample`、`PoseSample`、`DeviceHealth` | 允许丢包 |
| 视频 | TCP | `VideoFrame`（H.264 Annex-B） | 发送端只保留最新一帧 |
| 深度 | TCP | `DepthFrame`（uint16 mm + LZ4；协议预留 zstd） | 不丢 |
| 音频 | TCP（v6） | `AudioChunk`（PCM s16 / f32，单声道；时间戳 = 块内第一帧） | 不丢 |
| 全部数据（浏览器） | WebSocket（v5，`Hello.data_transport = WEBSOCKET`） | 同上，每帧一条 `DataMessage` | 同 TCP：视频积压丢非关键帧 |

TCP 流上的帧格式：`uint32 little-endian length` + `DataMessage` bytes。UDP 上每个数据报就是一条 `DataMessage`，不分片（超过 MTU 的消息走 TCP）。

## 连接流程（手机是服务端）

1. 手机发布 Bonjour 服务 `_imuninn._tcp`（名字 = 设备名，TXT `proto=<版本>`），监听控制端口 7420（WebSocket）和数据端口 7422（TCP）。
2. PC 发现或手输地址后打开控制 WebSocket，发 `Hello`（客户端名、自己接收 UDP 的端口）；手机回 `Welcome`（设备信息、能力描述 + 当前配置、TCP 端口、`client_id`）。
3. PC 连手机的 TCP 数据端口，先写 4 字节 LE `client_id`，之后收视频 / 深度流。位姿 / IMU / 健康由手机发到 PC 的 UDP 端口。
   浏览器没有裸 TCP / UDP：`Hello.data_transport = TRANSPORT_WEBSOCKET` 时，客户端改为对控制端口再开一条 WebSocket，第一帧发二进制 `"IMDATA01"` + 4 字节 LE `client_id`，之后所有订阅的流都作为二进制 `DataMessage` 帧从这条连接收。
4. `Subscribe` 订阅流；`SessionControl START` 开始采集。多个 PC 可同时连接，各自订阅。
5. 配置修改走 `SetConfig`（部分更新 + `base_config_version`）→ `ConfigResult` → 广播 `ConfigChanged` 给所有客户端。同一时刻只有持有租约（`Lease`）的客户端能改配置。

## 坐标系

线上数据一律是平台原生坐标系，手机端不做换算：

- 位姿是 ARKit 的 `ARCamera.transform`：右手系、世界 Y 向上、相机朝 -Z。
- IMU 在 Core Motion 设备系（竖屏 x 右、y 上、z 屏外），加速度保留平台符号（iOS 平放 z ≈ −9.81，Android ≈ +9.81）。
- 图像按传感器原始方向发送，`rotation_deg` 说明显示时要顺时针转多少度，内参跟图像同方向；v7 起每帧还带镜头（`camera`）和是否镜像（`mirrored`）。

客户端用 `protocol/frames/` 里的共享常数在入口换算到统一坐标系（`world` z 朝上、`device`、`cam_*_optical` 为 OpenCV 轴向、IMU 按 REP 145）。v7 起手机在 `DeviceInfo.frame_convention` 报告约定版本（当前 1），并在 `ar_capture_device_type` 报告 AR 追踪用的镜头。Python 包默认输出统一坐标系，见 [Python · 坐标系](../docs/python/11-frames.md)。

## 代码生成

```bash
tools/gen-proto.sh
```

生成 Python、C++、Swift、Java 绑定，并把 `imuninn.proto` 复制进 Python 包。Python 绑定提交在仓库里（安装不需要 protoc，CI 检查它与 `.proto` 一致）；其余语言的生成产物不入库。
