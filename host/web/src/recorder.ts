// Record the live streams to an MCAP file in the browser, the same layout `imuninn record`
// writes (host/python/src/imuninn/mcap_io.py): one topic per stream, the phone's protobuf
// messages as received, log_time = PC wall clock, publish_time = device time. The result
// opens in `imuninn rerun --mcap`, `imuninn info`, Foxglove, and this page.
import { McapWriter } from "@mcap/core";
import descriptor from "protobufjs/ext/descriptor";
import { root, T, type Body } from "./proto";
import { pcTimeNs } from "./phone";

const TOPIC: Record<Body["kind"], [string, string]> = {
  imu: ["/imu", "ImuSample"], pose: ["/ar_pose", "PoseSample"], video: ["/rgb", "VideoFrame"], depth: ["/depth", "DepthFrame"],
  gap: ["/gap", "Gap"], config_changed: ["/config", "ConfigChanged"], health: ["/health", "DeviceHealth"], audio: ["/audio", "AudioChunk"],
};

/** FileDescriptorSet of imuninn.proto, the schema payload MCAP's "protobuf" encoding expects. */
function descriptorSet(): Uint8Array {
  const set = (root as any).toDescriptor("proto3");
  for (const f of set.file ?? []) if (!f.name) f.name = "imuninn.proto";
  return descriptor.FileDescriptorSet.encode(set).finish();
}

interface Sink { write(b: Uint8Array): Promise<void>; finish(name: string): Promise<void> }

/** Chrome / Edge: stream straight to a file the user picked. */
class FileSink implements Sink {
  constructor(private stream: FileSystemWritableFileStream) {}
  async write(b: Uint8Array): Promise<void> { await this.stream.write(b as BufferSource as any); }
  async finish(): Promise<void> { await this.stream.close(); }
}

/** Everywhere else: keep the file in memory and hand it over as a download at the end. */
class MemorySink implements Sink {
  private parts: Uint8Array[] = [];
  async write(b: Uint8Array): Promise<void> { this.parts.push(b.slice()); }
  async finish(name: string): Promise<void> {
    const url = URL.createObjectURL(new Blob(this.parts as BlobPart[], { type: "application/octet-stream" }));
    const a = document.createElement("a");
    a.href = url; a.download = name; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
    this.parts = [];
  }
}

export function defaultRecordingName(): string {
  const d = new Date(), p = (n: number) => String(n).padStart(2, "0");
  return `imuninn-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.mcap`;
}

export class McapRecorder {
  count = 0;
  bytes = 0;
  readonly startedAt = performance.now();
  /** True when the file is held in memory until stop (no File System Access API). */
  inMemory = false;
  private writer!: McapWriter;
  private sink!: Sink;
  private channels = new Map<string, number>();
  private schema = descriptorSet();
  private chain: Promise<void> = Promise.resolve();   // McapWriter calls must not overlap
  private failed: unknown = null;
  private closed = false;
  name = defaultRecordingName();

  /** Ask where to save (when the browser can), write the header and the /device, /capabilities records. */
  static async start(device: Uint8Array | null, capabilities: Uint8Array | null): Promise<McapRecorder> {
    const r = new McapRecorder();
    const picker = (window as any).showSaveFilePicker as undefined | ((o: object) => Promise<FileSystemFileHandle>);
    if (picker) {
      const handle = await picker({ suggestedName: r.name, types: [{ description: "MCAP", accept: { "application/octet-stream": [".mcap"] } }] });
      r.name = handle.name;
      r.sink = new FileSink(await handle.createWritable());
    } else { r.sink = new MemorySink(); r.inMemory = true; }
    let pos = 0n;
    r.writer = new McapWriter({
      writable: { position: () => pos, write: async (b: Uint8Array) => { pos += BigInt(b.byteLength); r.bytes = Number(pos); await r.sink.write(b); } },
    });
    await r.writer.start({ profile: "", library: "imuninn-web" });
    const now = pcTimeNs();
    if (device) r.enqueue("/device", "DeviceInfo", device, now, 0n);
    if (capabilities) r.enqueue("/capabilities", "Capabilities", capabilities, now, 0n);
    return r;
  }

  private async channel(topic: string, type: string): Promise<number> {
    let id = this.channels.get(topic);
    if (id == null) {
      const schemaId = await this.writer.registerSchema({ name: `imuninn.v1.${type}`, encoding: "protobuf", data: this.schema });
      id = await this.writer.registerChannel({ topic, schemaId, messageEncoding: "protobuf", metadata: new Map() });
      this.channels.set(topic, id);
    }
    return id;
  }

  private enqueue(topic: string, type: string, data: Uint8Array, logTime: bigint, publishTime: bigint): void {
    if (this.closed) return;
    const copy = data.slice();   // the WebSocket frame buffer is not ours to keep
    const sequence = this.count++;
    this.chain = this.chain.then(async () => {
      if (this.failed) return;
      try {
        const channelId = await this.channel(topic, type);
        await this.writer.addMessage({ channelId, sequence, logTime, publishTime, data: copy });
      } catch (e) { this.failed = e; }
    });
  }

  /** Append one data frame. `clockOffsetNs` (pc - device) stamps log_time; without it, the wall clock now. */
  write(kind: Body["kind"], payload: Uint8Array, deviceTimeNs: number, clockOffsetNs: bigint | null): void {
    const [topic, type] = TOPIC[kind];
    const publish = BigInt(Math.round(deviceTimeNs || 0));
    const log = clockOffsetNs != null && publish > 0n ? publish + clockOffsetNs : pcTimeNs();
    this.enqueue(topic, type, payload, log, publish);
  }

  /** Record the configuration in effect on /config (at start and on every change). */
  writeConfig(config: object): void {
    const payload = T.ConfigChanged.encode(T.ConfigChanged.fromObject({ config })).finish();
    this.enqueue("/config", "ConfigChanged", payload, pcTimeNs(), 0n);
  }

  get error(): unknown { return this.failed; }
  get seconds(): number { return (performance.now() - this.startedAt) / 1000; }

  /** Finish the index and close the file (or start the download). */
  async stop(): Promise<void> {
    this.closed = true;
    await this.chain;
    await this.writer.end();
    await this.sink.finish(this.name);
    if (this.failed) throw this.failed;
  }
}
