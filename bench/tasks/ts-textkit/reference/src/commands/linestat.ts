import type { Result } from "./wordstat.js";

export function run(args: string[], input: string): Result {
  if (args.length) return { code: 2, out: "", err: "usage: textkit linestat\n" };
  const cp = (s: string) => [...s].length;
  const lines = input.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  const words = input.match(/\S+/gu)?.length ?? 0;
  const longest = lines.reduce((m, l) => Math.max(m, cp(l)), 0);
  return { code: 0, out: `lines ${lines.length}\nwords ${words}\nchars ${cp(input)}\nlongest ${longest}\n`, err: "" };
}
