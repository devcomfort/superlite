import { readFileSync } from "node:fs";
import { tokenize } from "./tokenize.js";
import { countWords } from "./count.js";
import { topN } from "./topn.js";

function usage(): never {
  process.stderr.write("usage: wordstat [--top N]\n");
  process.exit(2);
}

let top = 10;
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i++) {
  let value: string | undefined;
  if (args[i] === "--top") value = args[++i];
  else if (args[i].startsWith("--top=")) value = args[i].slice(6);
  else usage();
  if (value === undefined || !/^[0-9]+$/.test(value) || Number(value) < 1) usage();
  top = Number(value);
}

const text = readFileSync(0, "utf8");
const out = topN(countWords(tokenize(text)), top).map(([w, c]) => `${w} ${c}\n`).join("");
process.stdout.write(out);
