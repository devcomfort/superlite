import { StageError, type Args, type Rec } from "../types.js";
import { parseDuration } from "../duration.js";

export function dedupe(records: Rec[], args: Args): Rec[] {
  for (const key of Object.keys(args)) {
    if (key !== "window") throw new StageError(`dedupe: unknown argument ${key}`);
  }
  const window = parseDuration(args.window ?? "5s");
  const open = new Map<string, { rec: Rec; n: number }>();
  const kept: { rec: Rec; n: number }[] = [];
  for (const r of records) {
    const key = JSON.stringify([r.service, r.level, r.msg]);
    const prev = open.get(key);
    if (prev && r.ts - prev.rec.ts >= 0 && r.ts - prev.rec.ts <= window) {
      prev.n++;
      continue;
    }
    const entry = { rec: r, n: 1 };
    open.set(key, entry);
    kept.push(entry);
  }
  return kept.map((e) => (e.n > 1 ? { ...e.rec, fields: { ...e.rec.fields, repeat: String(e.n) } } : e.rec));
}
