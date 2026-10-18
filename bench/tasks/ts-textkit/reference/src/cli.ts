import { readFileSync } from "node:fs";
import { run as wordstat, type Result } from "./commands/wordstat.js";
import { run as linestat } from "./commands/linestat.js";
import { run as csvsum } from "./commands/csvsum.js";
import { run as slugify } from "./commands/slugify.js";

const commands: Record<string, (a: string[], i: string) => Result> = { wordstat, linestat, csvsum, slugify };
const usage = "usage: textkit <wordstat|linestat|csvsum|slugify> [args]\n";

const [name, ...rest] = process.argv.slice(2);
if (name === "--help") {
  process.stdout.write(usage);
} else if (name === undefined || !Object.hasOwn(commands, name)) {
  process.stderr.write(usage);
  process.exit(2);
} else {
  const r = commands[name](rest, readFileSync(0, "utf8"));
  process.stdout.write(r.out);
  process.stderr.write(r.err);
  process.exit(r.code);
}
