import { StageError, type Args, type Rec } from "../types.js";

export function percentile(records: Rec[], args: Args): string {
  for (const key of Object.keys(args)) {
    if (key !== "field" && key !== "p" && key !== "by") throw new StageError(`percentile: unknown argument ${key}`);
  }
  const field = args.field;
  if (!field) throw new StageError("percentile: missing field");
  const ps = (args.p ?? "50,90,99").split(",").map((s) => s.trim());
  for (const p of ps) {
    if (!/^\d+(\.\d+)?$/.test(p) || Number(p) > 100) throw new StageError(`percentile: bad p ${p}`);
  }
  if (args.by !== undefined && args.by !== "service") throw new StageError(`percentile: bad by ${args.by}`);
  const groups = new Map<string, number[]>();
  for (const r of records) {
    if (!Object.hasOwn(r.fields, field)) continue;
    const raw = r.fields[field].trim();
    if (!/^-?\d+(\.\d+)?$/.test(raw)) continue;
    const g = args.by ? r.service : "all";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(Number(raw));
  }
  const names = [...groups.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  return names.map((g) => {
    const v = groups.get(g)!.sort((a, b) => a - b);
    const cells = ps.map((p) => `p${p}=${v[Math.max(1, Math.ceil((Number(p) * v.length) / 100)) - 1]}`);
    return `${g} n=${v.length} ${cells.join(" ")}\n`;
  }).join("");
}
