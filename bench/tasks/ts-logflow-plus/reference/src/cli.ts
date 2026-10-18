import { readFileSync } from "node:fs";
import { runPipeline } from "./pipeline.js";
import { defaultRegistry } from "./registry.js";

const USAGE = "usage: logflow [--list] [--stage SPEC]... [--report SPEC] [--format F]\n";

function bad(): never {
  process.stderr.write(USAGE);
  process.exit(2);
}

const stages: string[] = [];
let report: string | undefined;
let format: string | undefined;
let list = false;
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i++) {
  let name = args[i];
  if (name === "--list") {
    list = true;
    continue;
  }
  let value: string | undefined;
  const eq = name.indexOf("=");
  if (name.startsWith("--") && eq > 0) {
    value = name.slice(eq + 1);
    name = name.slice(0, eq);
  }
  if (name !== "--stage" && name !== "--report" && name !== "--format") bad();
  if (value === undefined) value = args[++i];
  if (value === undefined) bad();
  if (name === "--stage") stages.push(value);
  else if (name === "--report") report = value;
  else format = value;
}

if (list) {
  process.stdout.write(defaultRegistry().list().map((l) => l + "\n").join(""));
} else {
  const r = runPipeline(readFileSync(0, "utf8"), { stages, report, format });
  process.stdout.write(r.out);
  process.stderr.write(r.err);
  process.exitCode = r.code;
}
