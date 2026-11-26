// Two-language UI (zh / en). Static text: elements with data-i18n / data-i18n-placeholder /
// data-i18n-title. Dynamic text: t(key). The choice is remembered in localStorage.

const dict = {
  zh: {
    title: "iMuninn Web Viewer",
    addr_placeholder: "手机地址，例如 10.0.0.5（App「服务」卡片里显示）",
    docs: "文档",
    connect: "连接", disconnect: "断开", start: "开始采集", stop: "停止",
    audio: "音频", audio_listen: "播放声音", audio_mute: "静音", audio_level: "电平", audio_underruns: "缓冲不足",
    depth: "深度", depth_ar_only: "深度只有 AR 模式才有", mode_ar: "AR 模式", mode_camera: "相机模式",
    orient: "画面", orient_auto: "自动（重力）", orient_portrait: "竖屏", orient_land_l: "横屏（左）", orient_land_r: "横屏（右）", orient_upside: "倒置",
    open_mcap: "打开 MCAP", replay_done: "回放结束", replay: "回放",
    video: "视频", depth_panel: "深度", pose: "位姿（3D，拖动旋转 · 滚轮缩放）", imu: "IMU", health: "设备状态", log: "日志",
    dropped: "丢", low_power: "低电量模式", via_relay: "经中继", direct: "直连",
    https_hint: "Safari 可直接连手机；Chrome / Edge 请运行",
    https_hint_tail: "，然后从 localhost 打开本页。",
    no_webcodecs: "此浏览器没有 WebCodecs，视频不能解码（Chrome / Edge / Safari 16.4+ 可用）",
    need_target: "请填手机地址，例如 10.0.0.5 或 10.0.0.5:7420",
    open_failed: "打开 MCAP 失败", thermal: "热状态", battery: "电量", phone_rates: "手机端速率", video_rate: "视频", uptime: "运行时间",
    grid: "网格 1 m", tracking: "追踪",
    subtitle_idle: "浏览器查看器 · 协议 v6", connection: "连接", preview: "预览", capture: "采集", mode: "模式",
    params: "手机参数", params_idle: "连接手机后，这里列出它的全部参数。", no_params: "这个流没有可调参数", restarts: "重启", restarts_title: "改这一项会重启手机的采集会话，各流短暂中断",
    p_failed: "失败", p_unchanged: "未变", p_rejected: "已拒绝", p_clamped: "已限幅为", p_restarted: "会话已重启",
    lease_title: "配置控制权：同一时间只有一个客户端能改参数", lease_free: "控制权空闲", lease_mine: "控制权在本页", lease_other: "控制权在", lease_take: "获取控制权", lease_release: "释放控制权",
    lease_denied: "没拿到控制权，当前持有者", lease_revoked: "手机收回了控制权", lease_blocked: "另一个客户端持有配置控制权",
    refresh: "刷新", refresh_title: "从手机重新读取参数和当前配置",
    profile: "预设", profile_apply: "应用", profile_load: "加载 YAML…", profile_save: "保存当前配置", profile_applied: "预设已应用", profile_bad: "预设文件无法解析",
    phone_rec_start: "手机端录制", phone_rec_stop: "停止手机端录制", phone_rec_title: "在手机上录制（.imuninn 文件，存到 App 的文档目录）",
    mcap_rec_start: "录制 MCAP", mcap_rec_stop: "停止录制", mcap_rec_title: "把本页收到的流录成 MCAP 文件（与 imuninn record 相同的格式）",
    rec_memory: "此浏览器不能边录边写文件，录制内容先留在内存里，停止时下载。长时间录制请用 Chrome / Edge 或 imuninn record。", rec_saved: "已保存", rec_failed: "录制失败", rec_messages: "条",
    time_sync: "时间同步", time_sync_title: "重新估计手机时钟与本机时钟的偏移（NTP 式，取 8 轮里往返最短的一次）", clock_offset: "时钟偏移（本机 − 手机）", clock_synced: "时钟已同步", clock_failed: "时间同步失败",
    dev_model: "型号", dev_os: "系统", dev_app: "App 版本", dev_protocol: "协议", dev_id: "设备 ID", dev_client: "本页客户端",
    session_restarted: "会话已重启", stale_retry: "配置版本过期，已重新读取并重试",
    pose_hz: "位姿", dropped_frames: "丢帧（本端）", st_disconnected: "未连接", st_connecting: "连接中", st_connected: "已连接", st_replay: "回放中", st_error: "连接失败",
  },
  en: {
    title: "iMuninn Web Viewer",
    addr_placeholder: "phone address, e.g. 10.0.0.5 (shown in the app's Server card)",
    docs: "Docs",
    connect: "Connect", disconnect: "Disconnect", start: "Start capture", stop: "Stop",
    audio: "Audio", audio_listen: "Play sound", audio_mute: "Mute", audio_level: "level", audio_underruns: "underruns",
    depth: "Depth", depth_ar_only: "Depth is only available in AR mode", mode_ar: "AR mode", mode_camera: "Camera mode",
    orient: "View", orient_auto: "Auto (gravity)", orient_portrait: "Portrait", orient_land_l: "Landscape (left)", orient_land_r: "Landscape (right)", orient_upside: "Upside down",
    open_mcap: "Open MCAP", replay_done: "replay finished", replay: "replay",
    video: "Video", depth_panel: "Depth", pose: "Pose (3D, drag to orbit · wheel to zoom)", imu: "IMU", health: "Device", log: "Log",
    dropped: "dropped", low_power: "low power mode", via_relay: "via relay", direct: "direct",
    https_hint: "Safari can connect to the phone directly; in Chrome / Edge run",
    https_hint_tail: " and open this page from localhost.",
    no_webcodecs: "No WebCodecs in this browser: video cannot be decoded (Chrome / Edge / Safari 16.4+)",
    need_target: "Enter the phone address, e.g. 10.0.0.5 or 10.0.0.5:7420",
    open_failed: "cannot open MCAP", thermal: "thermal", battery: "battery", phone_rates: "phone rates", video_rate: "video", uptime: "uptime",
    grid: "grid 1 m", tracking: "tracking",
    subtitle_idle: "browser viewer · protocol v6", connection: "Connection", preview: "Preview", capture: "Capture", mode: "Mode",
    params: "Phone settings", params_idle: "Connect to a phone to list all of its parameters here.", no_params: "No adjustable parameters on this stream", restarts: "restart", restarts_title: "Changing this restarts the capture session on the phone; streams pause briefly",
    p_failed: "failed", p_unchanged: "unchanged", p_rejected: "rejected", p_clamped: "clamped to", p_restarted: "session restarted",
    lease_title: "Config lease: one client at a time may change parameters", lease_free: "Lease free", lease_mine: "Lease held here", lease_other: "Lease held by", lease_take: "Take control", lease_release: "Release control",
    lease_denied: "Lease denied, held by", lease_revoked: "The phone revoked the lease", lease_blocked: "Another client holds the config lease",
    refresh: "Refresh", refresh_title: "Re-read parameters and the current config from the phone",
    profile: "Profile", profile_apply: "Apply", profile_load: "Load YAML…", profile_save: "Save current config", profile_applied: "profile applied", profile_bad: "cannot parse the profile",
    phone_rec_start: "Record on phone", phone_rec_stop: "Stop phone recording", phone_rec_title: "Record on the phone (.imuninn file in the app's Documents)",
    mcap_rec_start: "Record MCAP", mcap_rec_stop: "Stop recording", mcap_rec_title: "Record the streams this page receives to an MCAP file (same format as imuninn record)",
    rec_memory: "This browser cannot write the file while recording: it is kept in memory and downloaded on stop. For long recordings use Chrome / Edge or imuninn record.", rec_saved: "saved", rec_failed: "recording failed", rec_messages: "msgs",
    time_sync: "Sync clock", time_sync_title: "Re-estimate the offset between the phone clock and this computer (NTP-style, lowest round trip of 8)", clock_offset: "clock offset (this computer − phone)", clock_synced: "clock synced", clock_failed: "time sync failed",
    dev_model: "Model", dev_os: "OS", dev_app: "App version", dev_protocol: "Protocol", dev_id: "Device ID", dev_client: "This client",
    session_restarted: "session restarted", stale_retry: "stale config version: re-read and retried",
    pose_hz: "Pose", dropped_frames: "Dropped (here)", st_disconnected: "Disconnected", st_connecting: "Connecting", st_connected: "Connected", st_replay: "Replaying", st_error: "Connection failed",
  },
};
export type Lang = keyof typeof dict;
type Key = keyof typeof dict.zh;

let lang: Lang = (localStorage.getItem("imuninn.lang") as Lang) || (navigator.language.startsWith("zh") ? "zh" : "en");

export function t(key: Key): string { return dict[lang][key] ?? dict.zh[key] ?? key; }
export function currentLang(): Lang { return lang; }

export function applyLang(next?: Lang): void {
  if (next) { lang = next; try { localStorage.setItem("imuninn.lang", next); } catch { /* private mode */ } }
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.querySelectorAll<HTMLElement>("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n as Key); });
  document.querySelectorAll<HTMLElement>("[data-i18n-placeholder]").forEach((el) => { (el as HTMLInputElement).placeholder = t(el.dataset.i18nPlaceholder as Key); });
  document.querySelectorAll<HTMLElement>("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle as Key); });
  const d = document.getElementById("docs-link") as HTMLAnchorElement | null;
  if (d) d.href = lang === "zh" ? "https://imuninn.projects.weijinqi.com/" : "https://imuninn.projects.weijinqi.com/en/";
  const b = document.getElementById("lang");
  if (b) b.textContent = lang === "zh" ? "EN" : "中";
}
