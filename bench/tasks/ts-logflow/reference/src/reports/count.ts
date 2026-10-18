import { StageError, type Args, type Rec } from "../types.js";

export function count(records: Rec[], args: Args): string {
  for (const key of Object.keys(args)) {
    if (key !== "by" && key !== "limit") throw new StageError(`count: unknown argument ${key}`);
  }
  const by = args.by;
  let key: (r: Rec) => string | undefined;
  if (by === "service") key = (r) => r.service;
  else if (by === "level") key = (r) => r.level;
  else if (by === "minute") key = (r) => new Date(r.ts).toISOString().slice(0, 16);
  else if (by !== undefined && by.startsWith("field:") && by.length > 6) {
    const name = by.slice(6);
    key = (r) => (Object.hasOwn(r.fields, name) ? r.fields[name] : undefined);
  } else throw new StageError(`count: bad or missing by`);
  let limit = Infinity;
  if (args.limit !== undefined) {
    if (!/^[1-9]\d*$/.test(args.limit)) throw new StageError(`count: bad limit ${args.limit}`);
    limit = Number(args.limit);
  }
  const tally = new Map<string, number>();
  for (const r of records) {
    const k = key(r);
    if (k !== undefined) tally.set(k, (tally.get(k) ?? 0) + 1);
  }
  const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
  return [...tally]
    .sort((a, b) => b[1] - a[1] || cmp(a[0], b[0]))
    .slice(0, limit)
    .map(([k, n]) => `${k} ${n}\n`)
    .join("");
}
