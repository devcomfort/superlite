import type { Result } from "./wordstat.js";

export function run(args: string[], input: string): Result {
  if (args.length) return { code: 2, out: "", err: "usage: textkit slugify\n" };
  const lines = input.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  const out = lines.map((l) => l.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "") + "\n");
  return { code: 0, out: out.join(""), err: "" };
}
