# Web 查看器

浏览器里看手机数据并控制手机：视频、深度、位姿轨迹、IMU 曲线、麦克风音频（可播放 + 电平曲线，协议 v6）、热状态 / 电量。页面是纯静态文件，直接连手机（协议 v5），能改手机的全部参数、录制 MCAP，也能拖入 MCAP 文件离线回放。

## 在线页面

**<https://imuninn-webviewer.projects.weijinqi.com>**

- **Safari（macOS / iPadOS / iOS）可以直接用**：打开页面，地址栏填手机 App「服务」卡片里显示的地址（如 `10.0.0.5`），点「连接」。
- **Chrome / Edge 连不上手机**：出于安全策略，公网页面不能访问局域网地址，也拿不到视频解码器。用下面两种方式之一。
- 离线回放 MCAP 在任何浏览器里都能用。

## Chrome / Edge：本地起一个

```bash
pip install imuninn
imuninn web                 # 在 http://localhost:7430 托管同一页面并打开浏览器
```

从 `localhost` 打开时浏览器把页面当作可信来源：视频能解码，也允许连局域网里的手机。页面本身仍然直连手机，这台电脑只负责提供页面。

:::caution[Chrome / Edge 的另一种办法：改浏览器 flag]
打开 `chrome://flags/#unsafely-treat-insecure-origin-as-secure`，填入 `http://imuninn-webviewer.projects.weijinqi.com`，重启浏览器，然后用 **http://** 打开在线页面。这会让浏览器把该站点当作安全来源，连接手机时会弹一次「允许访问本地网络」的提示。这是开发者选项，只建议在自己的电脑上用。
:::

## 为什么会这样

- Chrome / Edge 的 Local Network Access 规则：公网来源的 http 页面禁止访问 `10.x` / `192.168.x` 等局域网地址；https 页面可以申请权限，但又被混合内容规则禁止连 `ws://`。
- WebCodecs（H.264 解码）只在安全上下文提供：`https://`、`http://localhost`。
- Safari 目前两条限制都没有；Firefox 能连但没有 WebCodecs，视频面板会空着。

## 直连手机是怎么工作的

浏览器开不了裸 TCP / UDP，协议 v5 给了手机一条专给浏览器的路：页面先像 Python 客户端一样连手机的控制 WebSocket（7420）握手，`Hello.data_transport = WEBSOCKET`；再对同一端口开第二条 WebSocket，首帧发 `"IMDATA01"` + 4 字节 `client_id`，之后所有流作为二进制 `DataMessage` 帧从这条连接收。数据格式和 Python / C++ 完全相同（页面用 protobufjs 运行时解析同一个 `imuninn.proto`）。

## 控制手机

页面不只是看，Python 客户端能对手机做的事，这里都能做（直连手机时）：

| 功能 | 页面上的位置 | Python 里对应 |
| --- | --- | --- |
| 开始 / 停止采集 | 「连接」卡片的「开始采集 / 停止」 | `dev.start()` / `dev.stop()` |
| 选择接收哪些流 | 「连接」卡片底部的流标签 | `dev.subscribe()` |
| 全部参数（会话模式、黑屏、各流开关、IMU 频率、相机曝光 / 白平衡 / 对焦 / 变焦、深度、麦克风……） | 「手机参数」卡片，按流分组 | `dev.set("rgb.iso", 400)` |
| 应用 / 保存预设 | 「手机参数」卡片的「预设」一行 | `imuninn profile apply / save` |
| 配置控制权 | 「手机参数」卡片右上角 | `dev.acquire_lease()` / `release_lease()` |
| 重新读取参数和配置 | 「刷新」 | `dev.get_config()` |
| 时间同步 | 「时间同步」 | `dev.time_sync()` |
| 手机端录制（`.imuninn`） | 「手机端录制」 | `dev.start_recording()` / `stop_recording()` |
| 录成 MCAP | 「录制 MCAP」 | `imuninn record` |
| 设备信息、热状态、电量 | 「设备状态」卡片 | `dev.info` / `dev.health` |

- **参数面板是按手机上报的能力（`Capabilities`）生成的**：手机有什么参数就列什么，App 以后加了新参数，页面不用改。带「重启」标记的参数会重启采集会话，各流短暂中断。
- 改一个参数后，旁边显示手机的结论：`✓` 已应用；「已限幅为 …」表示超出范围被手机收到范围内；「已拒绝」会带上原因，并把控件恢复成手机上的当前值。手机 App 上或其他客户端改了参数，页面也会跟着更新。
- **控制权**：同一时间只有一个客户端能改参数。页面第一次改参数时自动拿到控制权；被别的客户端占着时，改动会失败并在日志里说明是谁占着。点「释放控制权」把它让出来，断开连接时也会自动释放。
- **预设**用的是和 Python 包相同的 YAML（`calibration`、`dataset`、`teleop`、`camera_wide`），也能加载自己的文件；「保存当前配置」下载一份可以直接给 `imuninn profile apply` 用的 YAML。
- **录制 MCAP** 写出的文件和 `imuninn record` 同一格式，`imuninn rerun --mcap`、`imuninn info`、`imuninn export-audio` 都能读。Chrome / Edge 会先让你选保存位置，边录边写盘；Safari / Firefox 没有这个接口，内容先留在内存里，停止时一次下载，所以长时间录制请用 Chrome / Edge 或 `imuninn record`。只录页面订阅了的流。

只有 Python 命令行才有的：局域网自动发现（`imuninn list`，浏览器做不了 mDNS，所以页面里要手填地址）、Rerun 可视化、`.imuninn` 转 MCAP、导出 WAV。

## 界面

- 流标签控制这个浏览器收哪些流（不影响手机端）；「开始采集 / 停止」、模式、「深度」和「音频」开关直接发给手机，其余参数见上一节。
- 深度色标按每帧 98 分位自动定量程（右上角显示上限）。
- 「打开 MCAP」或把 `.mcap` 拖到页面上：本地回放，支持播放 / 暂停、拖动进度、倍速。
- 面板右上角显示实测频率、计数和按 `seq` 检测的丢帧数。

真机实测（iPhone 17 Pro，Wi‑Fi）：1920×1440@60 H.264 在浏览器里解码显示 60 fps，位姿 60 Hz、IMU 100 Hz、LiDAR 深度 60 Hz 同时显示。

## 浏览器要求

- 视频解码用 WebCodecs（H.264 Annex‑B 直接喂 `VideoDecoder`）：Chrome / Edge 94+（需 localhost 或 https）、Safari 16.4+。
- 深度是 Apple 分块 LZ4，页面里用一个小的 JS 解码器解；MCAP 的 zstd 分块用 `fzstd`。
- 位姿只画俯视 X–Z 轨迹和朝向（ARKit 坐标，Y 向上），不做 3D。

## 自己构建

```bash
cd host/web && npm install && npm run build      # 生成 host/web/dist
imuninn web --static host/web/dist               # 或任何静态服务器，从 localhost 打开
```
