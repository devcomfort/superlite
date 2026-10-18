export type Result = { code: number; out: string; err: string };
const usage = (): Result => ({ code: 2, out: "", err: "usage: textkit wordstat [--top N]\n" });

export function run(args: string[], input: string): Result {
  let top = 10;
  for (let i = 0; i < args.length; i++) {
    let v: string | undefined;
    if (args[i] === "--top") v = args[++i];
    else if (args[i].startsWith("--top=")) v = args[i].slice(6);
    else return usage();
    if (v === undefined || !/^[0-9]+$/.test(v) || Number(v) < 1) return usage();
    top = Number(v);
  }
  const counts = new Map<string, number>();
  for (const t of input.toLowerCase().match(/\p{L}+/gu) ?? []) counts.set(t, (counts.get(t) ?? 0) + 1);
  const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
  const rows = [...counts].sort((a, b) => b[1] - a[1] || cmp(a[0], b[0])).slice(0, top);
  return { code: 0, out: rows.map(([w, c]) => `${w} ${c}\n`).join(""), err: "" };
}
