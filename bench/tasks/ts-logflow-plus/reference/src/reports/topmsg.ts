import { StageError, type Args, type Rec } from "../types.js";

export function topmsg(records: Rec[], args: Args): string {
  for (const key of Object.keys(args)) {
    if (key !== "n") throw new StageError(`topmsg: unknown argument ${key}`);
  }
  if (args.n !== undefined && !/^[1-9]\d*$/.test(args.n)) throw new StageError(`topmsg: bad n ${args.n}`);
  const n = args.n === undefined ? 5 : Number(args.n);
  const tally = new Map<string, number>();
  for (const r of records) {
    const t = r.msg.replace(/0x[0-9a-fA-F]+/g, "<hex>").replace(/\d+(?:\.\d+)?/g, "<n>");
    tally.set(t, (tally.get(t) ?? 0) + 1);
  }
  return [...tally]
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .slice(0, n)
    .map(([t, c]) => `${c} ${t}\n`)
    .join("");
}
