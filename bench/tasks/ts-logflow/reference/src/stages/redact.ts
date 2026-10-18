import { StageError, type Args, type Rec } from "../types.js";

const RULES = ["email", "ip", "secret"];
const SECRET_KEYS = new Set(["password", "passwd", "secret", "token", "api_key", "apikey", "authorization"]);
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
const OCTET = "(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)";
const IP = new RegExp(`(?<![\\d.])(${OCTET})\\.(?:${OCTET}\\.){2}${OCTET}(?!\\d)`, "g");
const SECRET_MSG = /\b(password|passwd|secret|token|api_key|apikey)=\S+/gi;

export function redact(records: Rec[], args: Args): Rec[] {
  for (const key of Object.keys(args)) {
    if (key !== "rules" && key !== "mask") throw new StageError(`redact: unknown argument ${key}`);
  }
  const rules = args.rules === undefined ? RULES : args.rules.split(",");
  for (const rule of rules) {
    if (!RULES.includes(rule)) throw new StageError(`redact: unknown rule ${rule}`);
  }
  const mask = args.mask ?? "***";
  const on = new Set(rules);
  const text = (s: string): string => {
    if (on.has("email")) s = s.replace(EMAIL, () => mask);
    if (on.has("ip")) s = s.replace(IP, "$1.*.*.*");
    return s;
  };
  return records.map((r) => {
    const fields: Record<string, string> = {};
    for (const [k, v] of Object.entries(r.fields)) {
      fields[k] = on.has("secret") && SECRET_KEYS.has(k.toLowerCase()) ? mask : text(v);
    }
    let msg = text(r.msg);
    if (on.has("secret")) msg = msg.replace(SECRET_MSG, (_m, key: string) => `${key}=${mask}`);
    return { ...r, msg, fields };
  });
}
