// Parameter panel generated from the phone's self-describing Capabilities (ParamSpec):
// one group per stream plus the session-level switches, one control per parameter. Adding a
// parameter on the phone needs no change here. Edits go out as a partial SetConfig; the
// phone's verdict (applied / clamped / rejected) is shown next to the control.
import { currentLang, t } from "./i18n";
import { APPLY_RESTART, KIND, valueOf, type Capabilities, type ConfigResult, type DeviceConfig, type ParamSpec, type Scalar } from "./phone";

// The phone sends English labels; Chinese ones for the parameters known today. Unknown keys
// fall back to the phone's label.
const ZH: Record<string, string> = {
  "session": "会话", "imu": "IMU", "ar_pose": "位姿（AR）", "rgb": "视频", "depth": "深度", "audio": "音频（麦克风）", "health": "设备状态",
  "session.mode": "会话模式", "session.black_screen": "采集时黑屏",
  "imu.rate_hz": "IMU 频率", "imu.raw": "原始传感器（未校准）",
  "ar_pose.video_format": "AR 视频格式",
  "rgb.lens": "镜头（仅相机模式）", "rgb.camera_format": "相机格式（仅相机模式）", "rgb.bitrate_kbps": "H.264 码率", "rgb.keyframe_interval": "关键帧间隔",
  "rgb.exposure_mode": "曝光", "rgb.iso": "ISO（手动）", "rgb.exposure_ms": "快门（手动）", "rgb.exposure_bias": "曝光补偿",
  "rgb.white_balance_mode": "白平衡", "rgb.wb_temperature_k": "色温（手动）", "rgb.wb_tint": "色调（手动）",
  "rgb.focus_mode": "对焦", "rgb.lens_position": "镜头位置（手动）", "rgb.zoom": "变焦（相机模式）", "rgb.torch": "手电筒（相机模式）",
  "rgb.hdr": "视频 HDR（相机模式）", "rgb.low_light_boost": "低光增强（相机模式）", "rgb.stabilization": "防抖（相机模式；关闭时内参最准）",
  "health.rate_hz": "状态上报频率",
  "audio.sample_rate": "采样率", "audio.sample_format": "采样格式", "audio.chunk_ms": "分块时长", "audio.processing": "输入处理（raw = 不做增益 / 降噪）",
  "depth.smoothed": "时间平滑", "depth.compression": "压缩", "depth.rate_divisor": "每 N 帧发一帧",
};
const EN_GROUP: Record<string, string> = { session: "Session", imu: "IMU", ar_pose: "Pose (AR)", rgb: "Video", depth: "Depth", audio: "Audio (microphone)", health: "Device health" };

function labelFor(fullKey: string, fallback: string): string {
  if (currentLang() === "zh" && ZH[fullKey]) return ZH[fullKey];
  return fallback || fullKey;
}
function groupTitle(id: string): string { return (currentLang() === "zh" ? ZH[id] : EN_GROUP[id]) ?? id; }

function fmt(v: Scalar | undefined): string {
  if (v === undefined) return "";
  if (typeof v === "number" && !Number.isInteger(v)) return String(Number(v.toPrecision(6)));
  return String(v);
}

interface Row { key: string; spec: ParamSpec; read: () => Scalar; write: (v: Scalar) => void; inputs: HTMLElement[]; stat: HTMLElement; timer?: number }

export class ParamPanel {
  private rows = new Map<string, Row>();
  private enables = new Map<string, HTMLInputElement>();
  private caps: Capabilities | null = null;
  private config: DeviceConfig | null = null;
  /** Called with a dotted key and the new value; resolves with the phone's verdict (or null on failure). */
  onSet: ((key: string, value: Scalar) => Promise<ConfigResult | null>) | null = null;

  constructor(private box: HTMLElement) {}

  clear(): void { this.box.innerHTML = ""; this.rows.clear(); this.enables.clear(); this.caps = null; this.config = null; }

  /** Build the panel for these capabilities (again after a language switch or a refresh). */
  render(caps: Capabilities | null = this.caps, config: DeviceConfig | null = this.config): void {
    const open = new Set([...this.box.querySelectorAll<HTMLDetailsElement>("details[open]")].map((d) => d.dataset.group!));
    const first = !this.box.childElementCount;
    this.box.innerHTML = ""; this.rows.clear(); this.enables.clear();
    this.caps = caps; this.config = config;
    if (!caps) return;
    let saved: string[] | null = null;
    try { saved = JSON.parse(localStorage.getItem("imuninn.params.open") ?? "null"); } catch { /* ignore */ }
    const isOpen = (id: string) => (first ? (saved ?? ["session", "rgb"]).includes(id) : open.has(id));

    const session = caps.session_params.slice().sort((a, b) => (a.key === "mode" ? -1 : b.key === "mode" ? 1 : a.key.localeCompare(b.key)));
    if (session.length) this.group("session", session, false, isOpen("session"));
    for (const s of caps.streams) this.group(s.stream_id, s.params, true, isOpen(s.stream_id));
    if (config) this.sync(config);
  }

  private group(id: string, specs: ParamSpec[], hasEnable: boolean, open: boolean): void {
    const d = document.createElement("details");
    d.className = "pgroup"; d.dataset.group = id; d.open = open;
    d.ontoggle = () => {
      const ids = [...this.box.querySelectorAll<HTMLDetailsElement>("details[open]")].map((x) => x.dataset.group);
      try { localStorage.setItem("imuninn.params.open", JSON.stringify(ids)); } catch { /* private mode */ }
    };
    const sum = document.createElement("summary");
    const title = document.createElement("span");
    title.className = "pgroup-title"; title.textContent = groupTitle(id);
    const sub = document.createElement("span");
    sub.className = "caption"; sub.textContent = id === "session" ? "" : id;
    sum.append(title, sub);
    if (hasEnable) {
      const sw = document.createElement("label");
      sw.className = "field switch"; sw.title = `${id}.enabled`;
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.setAttribute("role", "switch"); cb.setAttribute("aria-label", `${id}.enabled`);
      const stat = document.createElement("span"); stat.className = "pstat";
      cb.onchange = () => void this.commit(`${id}.enabled`, cb.checked, stat, () => { cb.checked = this.currentEnabled(id); });
      sw.append(stat, cb);
      sw.onclick = (e) => e.stopPropagation();
      sum.append(sw);
      this.enables.set(id, cb);
    }
    d.append(sum);
    const body = document.createElement("div");
    body.className = "pbody";
    for (const spec of specs) body.append(this.row(id, spec));
    if (!specs.length) { const e = document.createElement("div"); e.className = "caption"; e.textContent = t("no_params"); body.append(e); }
    d.append(body);
    this.box.append(d);
  }

  private row(group: string, spec: ParamSpec): HTMLElement {
    const key = `${group}.${spec.key}`;
    const el = document.createElement("div");
    el.className = "prow";
    const k = document.createElement("label");
    k.className = "pk"; k.title = key;
    k.textContent = labelFor(key, spec.label);
    if (spec.apply === APPLY_RESTART) { const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = t("restarts"); tag.title = t("restarts_title"); k.append(" ", tag); }
    const v = document.createElement("div");
    v.className = "pv";
    const stat = document.createElement("div");
    stat.className = "pstat";
    const row: Row = { key, spec, read: () => "", write: () => undefined, inputs: [], stat };
    const commit = () => void this.commit(key, row.read(), stat, () => this.syncRow(row));
    const id = `p-${key}`;
    k.htmlFor = id;

    if (spec.kind === KIND.BOOL) {
      const cb = document.createElement("input");
      cb.type = "checkbox"; cb.id = id; cb.setAttribute("role", "switch");
      const wrap = document.createElement("span"); wrap.className = "field switch"; wrap.append(cb);
      row.read = () => cb.checked; row.write = (x) => { cb.checked = !!x; };
      cb.onchange = commit; row.inputs = [cb]; v.append(wrap);
    } else if (spec.kind === KIND.ENUM) {
      const sel = document.createElement("select");
      sel.className = "select"; sel.id = id;
      const fill = (extra?: string) => {
        sel.innerHTML = "";
        const choices = extra && !spec.choices.includes(extra) ? [extra, ...spec.choices] : spec.choices;
        for (const c of choices) { const o = document.createElement("option"); o.value = c; o.textContent = c; sel.append(o); }
      };
      fill();
      row.read = () => sel.value;
      // A value outside the advertised choices is still shown (camera formats depend on the lens).
      row.write = (x) => { const s = String(x); if (![...sel.options].some((o) => o.value === s)) fill(s); sel.value = s; };
      sel.onchange = commit; row.inputs = [sel]; v.append(sel);
    } else if (spec.kind === KIND.INT || spec.kind === KIND.FLOAT) {
      const num = document.createElement("input");
      num.type = "number"; num.className = "input num-input"; num.id = id;
      const ranged = spec.max > spec.min;
      const step = spec.step > 0 ? spec.step : spec.kind === KIND.INT ? 1 : 0;
      if (ranged) { num.min = String(spec.min); num.max = String(spec.max); }
      num.step = step ? String(step) : "any";
      row.inputs = [num];
      let slider: HTMLInputElement | null = null;
      if (ranged) {
        slider = document.createElement("input");
        slider.type = "range"; slider.className = "seek pslider"; slider.tabIndex = -1; slider.setAttribute("aria-hidden", "true");
        slider.min = String(spec.min); slider.max = String(spec.max);
        slider.step = String(step || (spec.max - spec.min) / 200);
        slider.oninput = () => { num.value = fmt(Number(slider!.value)); };
        slider.onchange = commit;
        row.inputs.push(slider);
        v.append(slider);
      }
      row.read = () => (spec.kind === KIND.INT ? Math.round(Number(num.value)) : Number(num.value));
      row.write = (x) => { num.value = fmt(x); if (slider) slider.value = String(x); };
      num.onchange = () => { if (num.value === "" || Number.isNaN(Number(num.value))) { this.syncRow(row); return; } if (slider) slider.value = num.value; commit(); };
      v.append(num);
    } else {
      const txt = document.createElement("input");
      txt.type = "text"; txt.className = "input"; txt.id = id; txt.spellcheck = false;
      row.read = () => txt.value; row.write = (x) => { txt.value = String(x); };
      txt.onchange = commit; row.inputs = [txt]; v.append(txt);
    }
    if (spec.unit) { const u = document.createElement("span"); u.className = "caption punit"; u.textContent = spec.unit; v.append(u); }
    if (spec.read_only) for (const i of row.inputs) (i as HTMLInputElement).disabled = true;
    const initial = valueOf(spec.current);
    if (initial !== undefined) row.write(initial);
    el.append(k, v, stat);
    this.rows.set(key, row);
    return el;
  }

  private currentEnabled(id: string): boolean { return !!this.config?.streams?.find((s) => s.stream_id === id)?.enabled; }

  private currentValue(row: Row): Scalar | undefined {
    const dot = row.key.indexOf(".");
    const group = row.key.slice(0, dot), key = row.key.slice(dot + 1);
    if (group === "session") {
      if (key === "mode") return this.config?.mode === 2 ? "camera" : this.config?.mode === 1 ? "ar" : undefined;
      return valueOf(this.config?.session_params?.[key]);
    }
    return valueOf(this.config?.streams?.find((s) => s.stream_id === group)?.params?.[key]);
  }

  private syncRow(row: Row): void { const v = this.currentValue(row); if (v !== undefined) row.write(v); }

  /** Bring every control to the phone's current config (skips the one being edited). */
  sync(config: DeviceConfig): void {
    this.config = config;
    const active = document.activeElement;
    for (const row of this.rows.values()) {
      if (row.inputs.includes(active as HTMLElement)) continue;
      const v = this.currentValue(row);
      // A verdict shown for an older value would mislead once the value has moved on.
      if (v !== undefined && fmt(v) !== fmt(row.read()) && !row.stat.classList.contains("muted")) row.stat.textContent = "";
      this.syncRow(row);
    }
    for (const [id, cb] of this.enables) cb.checked = this.currentEnabled(id);
  }

  private async commit(key: string, value: Scalar, stat: HTMLElement, revert: () => void): Promise<void> {
    if (!this.onSet) return;
    this.note(stat, "…", "muted");
    const res = await this.onSet(key, value);
    if (!res) { this.note(stat, t("p_failed"), "err"); revert(); return; }
    const f = res.fields.find((x) => x.key === key) ?? res.fields.find((x) => x.status === 3);
    if (!f) { this.note(stat, t("p_unchanged"), "muted"); return; }
    if (f.status === 3) { this.note(stat, `${t("p_rejected")}${f.reason ? `: ${f.reason}` : ""}`, "err", 8000); revert(); return; }
    const eff = valueOf(f.effective);
    if (f.status === 2) {
      this.note(stat, `${t("p_clamped")} ${fmt(eff)}`, "warn", 6000);
      const row = this.rows.get(key);
      if (row && eff !== undefined) row.write(eff);
    } else this.note(stat, res.session_restarted ? `✓ ${t("p_restarted")}` : "✓", "ok");
  }

  private notes = new WeakMap<HTMLElement, number>();
  private note(el: HTMLElement, text: string, tone: string, ms = 2500): void {
    el.textContent = text; el.className = `pstat ${tone}`; el.title = text;
    clearTimeout(this.notes.get(el));
    this.notes.set(el, window.setTimeout(() => { el.textContent = ""; el.title = ""; }, ms));
  }

  /** Grey the whole panel out (not connected / replay). */
  setEnabled(on: boolean): void { this.box.classList.toggle("disabled", !on); (this.box as any).inert = !on; }
}
