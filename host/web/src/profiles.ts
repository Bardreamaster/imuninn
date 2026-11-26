// Configuration presets as YAML, the same files and rules as the Python client
// (host/python/src/imuninn/profiles.py): `mode`, `session: {...}`, `streams: {id: {enabled, param...}}`.
// Everything is optional; only the listed keys are sent, as one partial SetConfig.
import { parse, stringify } from "yaml";
import { toValue, valueOf, KIND, type Capabilities, type DeviceConfig, type PbValue, type Scalar } from "./phone";

const files = import.meta.glob("../../python/src/imuninn/profiles/*.yaml", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

/** Built-in presets shipped with the Python package: name -> YAML text. */
export const BUILTIN: Record<string, string> = Object.fromEntries(
  Object.entries(files).map(([path, text]) => [path.split("/").pop()!.replace(/\.yaml$/, ""), text]).sort(([a], [b]) => a.localeCompare(b)),
);

export interface Profile { name?: string; mode?: string; session?: Record<string, Scalar>; streams?: Record<string, Record<string, Scalar> | null> }

export function parseProfile(text: string): Profile {
  // YAML 1.1, like PyYAML in the Python client: the same file means the same thing in both
  // (`yes` / `off` are booleans there; quote them to send a string).
  const data = parse(text, { version: "1.1" }) ?? {};
  if (typeof data !== "object" || Array.isArray(data)) throw new Error("profile must be a mapping");
  return data as Profile;
}

/** Profile -> partial DeviceConfig. Number kinds follow the phone's ParamSpec when known. */
export function toPatch(profile: Profile, caps: Capabilities | null): DeviceConfig {
  const patch: DeviceConfig = {};
  if (profile.mode) {
    if (profile.mode !== "ar" && profile.mode !== "camera") throw new Error(`mode must be ar or camera, not ${profile.mode}`);
    patch.mode = profile.mode === "camera" ? 2 : 1;
  }
  const kindOf = (stream: string | null, key: string) =>
    (stream === null ? caps?.session_params : caps?.streams.find((s) => s.stream_id === stream)?.params)?.find((p) => p.key === key)?.kind;
  for (const [key, value] of Object.entries(profile.session ?? {})) {
    (patch.session_params ??= {})[key] = fill(value, kindOf(null, key));
  }
  for (const [id, params] of Object.entries(profile.streams ?? {})) {
    const sc: { stream_id: string; enabled?: boolean; params?: Record<string, PbValue> } = { stream_id: String(id) };
    for (const [key, value] of Object.entries(params ?? {})) {
      if (key === "enabled") sc.enabled = !!value;
      else (sc.params ??= {})[key] = fill(value, kindOf(id, key));
    }
    (patch.streams ??= []).push(sc);
  }
  return patch;
}

function fill(value: Scalar, kind: number | undefined): PbValue {
  // YAML has one number type: "100" for a float parameter must still go out as a double,
  // and an enum whose choices look like numbers ("48000") as a string.
  if (typeof value === "number" && (kind === KIND.ENUM || kind === KIND.STRING)) return { s: String(value) };
  return toValue(value, kind);
}

/** Current DeviceConfig -> profile (what is in effect now). */
export function fromConfig(config: DeviceConfig, name = "snapshot"): Profile {
  const out: Profile = { name, mode: config.mode === 2 ? "camera" : "ar" };
  const session = Object.entries(config.session_params ?? {});
  if (session.length) out.session = Object.fromEntries(session.map(([k, v]) => [k, valueOf(v) as Scalar]));
  out.streams = {};
  for (const sc of config.streams ?? []) {
    const d: Record<string, Scalar> = { enabled: !!sc.enabled };
    for (const [k, v] of Object.entries(sc.params ?? {})) d[k] = valueOf(v) as Scalar;
    out.streams[sc.stream_id] = d;
  }
  return out;
}

/** YAML 1.1 output, so enum values like "off" come out quoted and PyYAML reads them back as strings. */
export function dumpProfile(profile: Profile): string { return stringify(profile, { version: "1.1" }); }
