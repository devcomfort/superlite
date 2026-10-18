import { StageError, type Args, type Rec, type Table } from "../types.js";
import { fmtNumber } from "../format.js";

const FNS = ["count", "sum", "avg", "min", "max"];

export function rollup(records: Rec[], args: Args): Table {
  for (const key of Object.keys(args)) {
    if (key !== "by" && key !== "fn" && key !== "field") throw new StageError(`rollup: unknown argument ${key}`);
  }
  const by = args.by;
  let keyOf: (r: Rec) => string | undefined;
  if (by === "service") keyOf = (r) => r.service;
  else if (by === "level") keyOf = (r) => r.level;
  else if (by === "minute") keyOf = (r) => new Date(r.ts).toISOString().slice(0, 16);
  else if (by !== undefined && by.startsWith("field:") && by.length > 6) {
    const name = by.slice(6);
    keyOf = (r) => (Object.hasOwn(r.fields, name) ? r.fields[name] : undefined);
  } else throw new StageError("rollup: bad or missing by");
  const fn = args.fn ?? "count";
  if (!FNS.includes(fn)) throw new StageError(`rollup: unknown fn ${fn}`);
  const field = args.field;
  if (fn !== "count" && !field) throw new StageError(`rollup: ${fn} needs field`);

  const groups = new Map<string, { n: number; sum: number; min: number; max: number }>();
  for (const r of records) {
    const key = keyOf(r);
    if (key === undefined) continue;
    let g = groups.get(key);
    if (fn === "count") {
      if (!g) groups.set(key, (g = { n: 0, sum: 0, min: 0, max: 0 }));
      g.n++;
      continue;
    }
    if (!Object.hasOwn(r.fields, field!)) continue;
    const raw = r.fields[field!].trim();
    if (!/^-?\d+(\.\d+)?$/.test(raw)) continue;
    const v = Number(raw);
    if (!g) groups.set(key, (g = { n: 0, sum: 0, min: v, max: v }));
    g.n++;
    g.sum += v;
    g.min = Math.min(g.min, v);
    g.max = Math.max(g.max, v);
  }
  const rows = [...groups]
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([key, g]) => {
      const value = fn === "count" ? String(g.n) : fn === "sum" ? fmtNumber(g.sum)
        : fn === "avg" ? fmtNumber(g.sum / g.n) : fn === "min" ? fmtNumber(g.min) : fmtNumber(g.max);
      return [key, value, String(g.n)];
    });
  return { columns: ["key", "value", "n"], rows };
}
