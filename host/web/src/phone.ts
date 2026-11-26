// Direct source (protocol v5): the browser talks to the phone itself, exactly like the
// Python client — control WebSocket with protobuf ControlMessage, then a second WebSocket
// to the same port announced with "IMDATA01" + uint32 LE client_id, on which every
// subscribed stream arrives as binary DataMessage frames.
//
// The control surface mirrors imuninn.PhoneClient (host/python/src/imuninn/client.py):
// set / setConfig, fetchCapabilities / fetchConfig, subscribe, start / stop,
// startRecording / stopRecording, acquireLease / releaseLease, timeSync.
import { decodeDataMessage, T, type Body } from "./proto";

export const PROTOCOL_VERSION = 7;
const TRANSPORT_WEBSOCKET = 3;
const MAGIC = new TextEncoder().encode("IMDATA01");

export type Scalar = boolean | number | string;
export interface PbValue { b?: boolean; i?: number; f?: number; s?: string }
export interface ParamSpec {
  key: string; label: string; unit: string;
  kind: number;              // 1 bool, 2 int, 3 float, 4 enum, 5 string
  apply: number;             // 1 immediate, 2 restarts the session
  min: number; max: number; step: number; choices: string[];
  current?: PbValue; default?: PbValue; read_only: boolean;
}
export interface StreamDescriptor { stream_id: string; kind: number; transport: number; params: ParamSpec[] }
export interface StreamConfig { stream_id: string; enabled?: boolean; params?: Record<string, PbValue> }
export interface DeviceConfig { config_version?: number; mode?: number; streams?: StreamConfig[]; session_params?: Record<string, PbValue> }
export interface Capabilities { device?: DeviceInfo; streams: StreamDescriptor[]; session_params: ParamSpec[]; config?: DeviceConfig }
export interface DeviceInfo { device_id?: string; device_name?: string; model?: string; platform?: number; os_version?: string; protocol_version?: number; app_version?: string; has_lidar?: boolean }
export interface FieldResult { key: string; status: number; effective?: PbValue; reason?: string }
export interface ConfigResult { config_version: number; fields: FieldResult[]; session_restarted: boolean }
export interface TimeSync { offsetNs: bigint; rttNs: bigint }

export const KIND = { BOOL: 1, INT: 2, FLOAT: 3, ENUM: 4, STRING: 5 } as const;
export const APPLY_RESTART = 2;
export const STATUS = ["?", "applied", "clamped", "rejected"];
const LEASE = { REQUEST: 1, RELEASE: 2, GRANTED: 3, DENIED: 4, REVOKED: 5 } as const;

export interface PhoneWelcome {
  device: DeviceInfo;
  capabilities: Capabilities;
  streams: { stream_id: string; kind: number }[];
  config: DeviceConfig;
  client_id: number;
  protocol_version: number;
}

/** Raised by set / setConfig when another client holds the configuration lease (phone replied 409). */
export class LeaseError extends Error {}

/** Plain value of a protobuf Value (undefined when unset). */
export function valueOf(v: PbValue | undefined | null): Scalar | undefined {
  if (!v) return undefined;
  return v.b ?? v.i ?? v.f ?? v.s;
}

/** Scalar -> protobuf Value. `kind` (ParamSpec.kind) settles int vs float; without it integers go as int64. */
export function toValue(value: Scalar, kind?: number): PbValue {
  if (typeof value === "boolean") return { b: value };
  if (typeof value === "number") return kind === KIND.FLOAT || !Number.isInteger(value) ? { f: value } : { i: value };
  return { s: String(value) };
}

/** Dotted key -> partial DeviceConfig, same rules as PhoneClient.set(). */
export function patchFor(key: string, value: Scalar, kind?: number): DeviceConfig {
  const dot = key.indexOf(".");
  const head = dot < 0 ? key : key.slice(0, dot), rest = dot < 0 ? "" : key.slice(dot + 1);
  if (head === "session" && rest === "mode") return { mode: value === "camera" ? 2 : 1 };
  if (head === "session") return { session_params: { [rest]: toValue(value, kind) } };
  if (rest === "enabled") return { streams: [{ stream_id: head, enabled: !!value }] };
  return { streams: [{ stream_id: head, params: { [rest]: toValue(value, kind) } }] };
}

/** Wall clock in nanoseconds (sub-millisecond where the browser allows it). */
export function pcTimeNs(): bigint {
  return BigInt(Math.round((performance.timeOrigin + performance.now()) * 1000)) * 1000n;
}

export class PhoneSource {
  private control: WebSocket | null = null;
  private data: WebSocket | null = null;
  private nextRequest = 1;
  private pending = new Map<number, (m: any) => void>();
  private queue: Promise<unknown> = Promise.resolve();   // config writes go one at a time
  clientName = "web-viewer";
  device: DeviceInfo | null = null;
  capabilities: Capabilities | null = null;
  config: DeviceConfig | null = null;
  clientId = 0;
  leaseHolder = "";                 // "" = free
  clock: TimeSync | null = null;    // offsetNs = pc - device
  /** Protobuf-encoded DeviceInfo / Capabilities from the handshake (for recordings). */
  deviceBytes: Uint8Array | null = null;
  capabilitiesBytes: Uint8Array | null = null;
  onBody: ((b: Body) => void) | null = null;
  /** Every data frame as received: body kind + the still-encoded inner message. */
  onRaw: ((kind: Body["kind"], payload: Uint8Array, body: Body) => void) | null = null;
  onWelcome: ((w: PhoneWelcome) => void) | null = null;
  onStatus: ((s: string) => void) | null = null;
  onConfig: ((cfg: DeviceConfig) => void) | null = null;
  onCapabilities: ((c: Capabilities) => void) | null = null;
  onLease: ((holder: string, event: string) => void) | null = null;
  onClose: (() => void) | null = null;

  /** `target`: "host" or "host:port" (default port 7420). */
  connect(target: string): void {
    this.close();
    const [host, port] = target.includes(":") && !target.startsWith("[") ? target.split(":") : [target, "7420"];
    const url = `ws://${host}:${port}/`;
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    this.control = ws;
    this.onStatus?.(`connecting ${url}`);
    ws.onerror = () => this.onStatus?.("websocket error (is the app open and on the same Wi-Fi?)");
    ws.onclose = (e) => { this.onStatus?.(`closed (${e.code})`); this.data?.close(); this.data = null; this.reset(); this.onClose?.(); };
    ws.onopen = async () => {
      try {
        const w = await this.request({ hello: { client: { name: this.clientName, version: "0.3" }, udp_port: 0, protocol_version: PROTOCOL_VERSION, data_transport: TRANSPORT_WEBSOCKET } });
        if (!w.welcome) throw new Error(`expected welcome, got ${Object.keys(w).join(",")}`);
        const welcome = w.welcome;
        if (welcome.protocol_version !== PROTOCOL_VERSION) this.onStatus?.(`protocol mismatch: phone v${welcome.protocol_version}, page v${PROTOCOL_VERSION}`);
        this.clientId = welcome.client_id ?? 0;
        this.device = welcome.device ?? {};
        this.adoptCapabilities(welcome.capabilities ?? {});
        this.deviceBytes = T.DeviceInfo.encode(T.DeviceInfo.fromObject(this.device!)).finish();
        this.openData(url, this.clientId);
        const streams = this.capabilities!.streams.map((s) => ({ stream_id: s.stream_id, kind: s.kind }));
        this.onWelcome?.({ device: this.device!, capabilities: this.capabilities!, streams, config: this.config!, client_id: this.clientId, protocol_version: welcome.protocol_version ?? 0 });
        this.subscribe(streams.map((s) => s.stream_id));
        this.onStatus?.("connected");
        void this.timeSync().catch(() => undefined);
      } catch (e) { this.onStatus?.(`handshake failed: ${e}`); ws.close(); }
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") return;
      const decoded = T.ControlMessage.decode(new Uint8Array(ev.data)) as any;
      // Time sync carries nanosecond wall-clock values beyond 2^53: keep those as strings.
      const m = T.ControlMessage.toObject(decoded, { longs: decoded.time_sync_pong ? String : Number, enums: Number, defaults: false, arrays: true, objects: true });
      const id = Number(m.request_id ?? 0);
      const cb = id ? this.pending.get(id) : undefined;
      if (cb) { this.pending.delete(id); cb(m); return; }
      if (m.config_changed) { this.config = m.config_changed.config ?? {}; this.onConfig?.(this.config!); }
      else if (m.error) this.onStatus?.(`phone error ${m.error.code}: ${m.error.message}`);
      else if (m.lease) this.onLeaseMessage(m.lease);
    };
  }

  private adoptCapabilities(c: any): void {
    this.capabilitiesBytes = T.Capabilities.encode(T.Capabilities.fromObject(c)).finish();
    this.capabilities = { device: c.device, streams: c.streams ?? [], session_params: c.session_params ?? [], config: c.config };
    // Zero-valued fields are absent on the wire (proto3): give every spec its full shape.
    const full = (p: Partial<ParamSpec>): ParamSpec => ({ key: "", label: "", unit: "", kind: 0, apply: 0, min: 0, max: 0, step: 0, read_only: false, ...p, choices: p.choices ?? [] });
    this.capabilities.session_params = this.capabilities.session_params.map(full);
    for (const s of this.capabilities.streams) s.params = (s.params ?? []).map(full);
    this.config = c.config ?? {};
  }

  private onLeaseMessage(l: { action?: number; holder?: string }): void {
    const holder = l.holder ?? "";
    if (l.action === LEASE.GRANTED) this.leaseHolder = holder;
    else if (l.action === LEASE.RELEASE || l.action === LEASE.REVOKED) this.leaseHolder = "";
    this.emitLease(["", "request", "release", "granted", "denied", "revoked"][l.action ?? 0] ?? String(l.action));
  }

  /** The phone both replies to and broadcasts a lease change: report each change once. */
  private lastLease = "";
  private lastLeaseAt = 0;
  private emitLease(event: string): void {
    const sig = `${event}:${this.leaseHolder}`, now = performance.now();
    if (sig === this.lastLease && now - this.lastLeaseAt < 1000) return;
    this.lastLease = sig; this.lastLeaseAt = now;
    this.onLease?.(this.leaseHolder, event);
  }

  private reset(): void {
    for (const cb of this.pending.values()) cb({ error: { code: 0, message: "connection closed" } });
    this.pending.clear();
    this.leaseHolder = ""; this.clock = null;
  }

  private openData(url: string, clientId: number): void {
    const d = new WebSocket(url);
    d.binaryType = "arraybuffer";
    this.data = d;
    d.onopen = () => {
      const hello = new Uint8Array(MAGIC.length + 4);
      hello.set(MAGIC);
      new DataView(hello.buffer).setUint32(MAGIC.length, clientId, true);
      d.send(hello);
    };
    d.onmessage = (ev) => {
      if (typeof ev.data === "string") return;
      const bytes = new Uint8Array(ev.data);
      const body = decodeDataMessage(bytes);
      if (!body) return;
      // Recording first: a display error must not cost a recorded sample.
      if (this.onRaw) { const inner = innerMessage(bytes); if (inner) this.onRaw(body.kind, inner, body); }
      this.onBody?.(body);
    };
    d.onclose = () => { if (this.data === d) { this.data = null; this.onStatus?.("data channel closed"); } };
  }

  private sendControl(msg: object): number {
    const id = this.nextRequest++;
    const payload = T.ControlMessage.encode(T.ControlMessage.fromObject({ request_id: id, ...msg })).finish();
    this.control?.send(payload);
    return id;
  }

  private request(msg: object, timeoutMs = 5000): Promise<any> {
    return new Promise((resolve, reject) => {
      if (this.control?.readyState !== WebSocket.OPEN) { reject(new Error("not connected")); return; }
      const id = this.sendControl(msg);
      const t = setTimeout(() => { this.pending.delete(id); reject(new Error("timeout")); }, timeoutMs);
      this.pending.set(id, (m) => { clearTimeout(t); resolve(m); });
    });
  }

  // ---------------------------------------------------------------- session
  subscribe(streams: string[], unsubscribe = false): void { this.sendControl({ subscribe: { stream_ids: streams, unsubscribe } }); }
  start(): void { this.sendControl({ session_control: { action: 1 } }); }
  stop(): void { this.sendControl({ session_control: { action: 2 } }); }
  /** Phone-side recording (.imuninn file in the app's Documents). */
  startRecording(): void { this.sendControl({ session_control: { action: 3 } }); }
  stopRecording(): void { this.sendControl({ session_control: { action: 4 } }); }

  // ---------------------------------------------------------------- configuration
  /** Parameter specs + current config, re-read from the phone. */
  async fetchCapabilities(): Promise<Capabilities> {
    const r = await this.request({ get_capabilities: {} });
    if (!r.capabilities) throw new Error(r.error?.message ?? "no capabilities in reply");
    this.adoptCapabilities(r.capabilities);
    this.onCapabilities?.(this.capabilities!);
    return this.capabilities!;
  }

  async fetchConfig(): Promise<DeviceConfig> {
    const r = await this.request({ get_config: {} });
    if (!r.config) throw new Error(r.error?.message ?? "no config in reply");
    this.config = r.config;
    this.onConfig?.(this.config!);
    return this.config!;
  }

  /** Send a partial config. Rejects with LeaseError on 409, Error on other phone errors. */
  setConfig(patch: DeviceConfig): Promise<ConfigResult> {
    // Serialised: each write is based on the version the previous one produced, so quick
    // successive edits are not rejected as stale.
    const run = async (): Promise<ConfigResult> => {
      const r = await this.request({ set_config: { base_config_version: this.config?.config_version ?? 0, patch } });
      if (r.error) {
        if (r.error.code === 409) throw new LeaseError(r.error.message);
        throw new Error(r.error.message || `error ${r.error.code}`);
      }
      const res: ConfigResult = { config_version: r.config_result?.config_version ?? 0, fields: r.config_result?.fields ?? [], session_restarted: !!r.config_result?.session_restarted };
      if (this.config && res.config_version) this.config.config_version = res.config_version;
      return res;
    };
    const p = this.queue.then(run, run);
    this.queue = p.catch(() => undefined);
    return p;
  }

  /** Set one parameter by dotted key ("depth.enabled", "rgb.iso", "session.mode"), like PhoneClient.set(). */
  set(key: string, value: Scalar): Promise<ConfigResult> {
    return this.setConfig(patchFor(key, value, this.spec(key)?.kind));
  }

  /** ParamSpec for a dotted key, from the capabilities. */
  spec(key: string): ParamSpec | undefined {
    const dot = key.indexOf(".");
    const head = key.slice(0, dot), rest = key.slice(dot + 1);
    if (head === "session") return this.capabilities?.session_params.find((p) => p.key === rest);
    return this.capabilities?.streams.find((s) => s.stream_id === head)?.params.find((p) => p.key === rest);
  }

  // ---------------------------------------------------------------- lease
  /** Ask for exclusive config control; true when granted. Released on disconnect. */
  async acquireLease(): Promise<boolean> {
    const r = await this.request({ lease: { action: LEASE.REQUEST, holder: this.clientName } });
    const granted = r.lease?.action === LEASE.GRANTED;
    this.leaseHolder = r.lease?.holder ?? "";
    this.emitLease(granted ? "granted" : "denied");
    return granted;
  }

  async releaseLease(): Promise<void> {
    const r = await this.request({ lease: { action: LEASE.RELEASE, holder: this.clientName } });
    this.leaseHolder = r.lease?.holder ?? "";
    this.emitLease("release");
  }

  // ---------------------------------------------------------------- clock
  /** NTP-style offset estimate; keeps the lowest-RTT sample of `rounds`. */
  async timeSync(rounds = 8): Promise<TimeSync | null> {
    let best: TimeSync | null = null;
    for (let i = 0; i < rounds; i++) {
      const t1 = pcTimeNs();
      let r: any;
      try { r = await this.request({ time_sync_ping: { client_send_ns: t1.toString() } }, 2000); } catch { continue; }
      const t4 = pcTimeNs();
      if (!r.time_sync_pong) continue;
      const t2 = BigInt(r.time_sync_pong.device_recv_ns ?? 0), t3 = BigInt(r.time_sync_pong.device_send_ns ?? 0);
      const rtt = (t4 - t1) - (t3 - t2);
      const offset = ((t2 - t1) + (t3 - t4)) / 2n;   // device - pc
      if (!best || rtt < best.rttNs) best = { offsetNs: -offset, rttNs: rtt };
      await new Promise((res) => setTimeout(res, 50));
    }
    if (best) this.clock = best;
    return best;
  }

  /** Device timestamp -> PC wall clock, nanoseconds (null until a time sync has run). */
  toPcTimeNs(deviceTimeNs: number | bigint): bigint | null {
    return this.clock ? BigInt(deviceTimeNs) + this.clock.offsetNs : null;
  }

  get open(): boolean { return this.control?.readyState === WebSocket.OPEN; }

  close(): void {
    const c = this.control, d = this.data;
    this.control = null; this.data = null;
    if (c) { c.onclose = null; c.close(); }
    if (d) { d.onclose = null; d.close(); }
    this.reset();
  }
}

/** The single length-delimited field of a DataMessage: its still-encoded inner message. */
function innerMessage(bytes: Uint8Array): Uint8Array | null {
  let p = 0;
  const varint = (): number => {
    let v = 0, shift = 0;
    for (;;) { const b = bytes[p++]; v += (b & 0x7f) * 2 ** shift; if (!(b & 0x80)) return v; shift += 7; }
  };
  if (!bytes.length) return null;
  const tag = varint();
  if ((tag & 7) !== 2) return null;
  const len = varint();
  return p + len <= bytes.length ? bytes.subarray(p, p + len) : null;
}
