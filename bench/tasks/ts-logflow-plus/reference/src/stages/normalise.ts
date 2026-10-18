import { StageError, type Args, type Rec } from "../types.js";
import { canonicalService, normaliseKey } from "../aliases.js";

const SWITCHES = ["service", "keys", "ws"];

export function normalise(records: Rec[], args: Args): Rec[] {
  for (const [key, value] of Object.entries(args)) {
    if (!SWITCHES.includes(key)) throw new StageError(`normalise: unknown argument ${key}`);
    if (value !== "on" && value !== "off") throw new StageError(`normalise: ${key} must be on or off`);
  }
  const on = (k: string) => args[k] !== "off";
  return records.map((r) => {
    const fields: Record<string, string> = {};
    for (const [k, v] of Object.entries(r.fields)) fields[on("keys") ? normaliseKey(k) : k] = v;
    return {
      ...r,
      service: on("service") ? canonicalService(r.service) : r.service,
      msg: on("ws") ? r.msg.replace(/\s+/g, " ").trim() : r.msg,
      fields,
    };
  });
}
