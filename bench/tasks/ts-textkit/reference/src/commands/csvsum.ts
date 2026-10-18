import type { Result } from "./wordstat.js";

const fail = (code: number, err: string): Result => ({ code, out: "", err: err + "\n" });
const USAGE = "usage: textkit csvsum --col NAME";

export function run(args: string[], input: string): Result {
  let col: string | undefined;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--col") col = args[++i];
    else if (args[i].startsWith("--col=")) col = args[i].slice(6);
    else return fail(2, USAGE);
    if (col === undefined) return fail(2, USAGE);
  }
  if (col === undefined) return fail(2, USAGE);
  const lines = input.split("\n").map((l) => l.replace(/\r$/, "")).filter((l) => l.trim() !== "");
  if (!lines.length) return fail(3, "error: no header");
  const idx = lines[0].split(",").map((c) => c.trim()).indexOf(col);
  if (idx < 0) return fail(3, "error: no such column");
  let sum = 0;
  for (let r = 1; r < lines.length; r++) {
    const cell = (lines[r].split(",")[idx] ?? "").trim();
    if (cell === "") continue;
    if (!/^-?\d+(\.\d+)?$/.test(cell)) return fail(3, `error: row ${r}: not a number`);
    sum += Number(cell);
  }
  return { code: 0, out: String(Number(sum.toFixed(6)) + 0) + "\n", err: "" };
}
