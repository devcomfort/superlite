import { StageError, type Args, type Rec } from "../types.js";
import { levelRank, normalizeLevel } from "../levels.js";
import { parseDuration } from "../duration.js";

const KNOWN = new Set(["level", "service", "since", "until", "grep", "field"]);
const escape = (s: string) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&");

function glob(patterns: string): RegExp {
  const alts = patterns.split(",").map((p) => p.split("*").map(escape).join(".*"));
  return new RegExp(`^(?:${alts.join("|")})$`, "s");
}

function bound(text: string, latest: number): number {
  if (/^@\d+$/.test(text)) return Number(text.slice(1));
  return latest - parseDuration(text);
}

export function filter(records: Rec[], args: Args): Rec[] {
  for (const key of Object.keys(args)) {
    if (!KNOWN.has(key)) throw new StageError(`filter: unknown argument ${key}`);
  }
  let min: number | null = null;
  if (args.level !== undefined) {
    const level = normalizeLevel(args.level);
    if (!level) throw new StageError(`filter: unknown level ${args.level}`);
    min = levelRank(level);
  }
  const service = args.service !== undefined ? glob(args.service) : null;
  const latest = records.reduce((m, r) => Math.max(m, r.ts), -Infinity);
  const since = args.since !== undefined ? bound(args.since, latest) : null;
  const until = args.until !== undefined ? bound(args.until, latest) : null;
  let fieldKey = "";
  let fieldValue = "";
  if (args.field !== undefined) {
    const i = args.field.indexOf("=");
    if (i < 1) throw new StageError(`filter: bad field ${args.field}`);
    fieldKey = args.field.slice(0, i);
    fieldValue = args.field.slice(i + 1);
  }
  return records.filter((r) =>
    (min === null || levelRank(r.level) >= min) &&
    (service === null || service.test(r.service)) &&
    (since === null || r.ts >= since) &&
    (until === null || r.ts < until) &&
    (args.grep === undefined || r.msg.includes(args.grep)) &&
    (args.field === undefined || (Object.hasOwn(r.fields, fieldKey) && r.fields[fieldKey] === fieldValue)));
}
