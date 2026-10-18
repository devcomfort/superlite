import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SitegenError } from "./errors.js";
import { findBrokenLinks } from "./links.js";
import { build } from "./site.js";

export interface IO {
  out(text: string): void;
  err(text: string): void;
}

const USAGE = `usage: sitegen [-h] {build,check} ...

Static site generator

commands:
  build SRC OUT   build a site
  check OUT       check built output for broken links
`;

function walk(dir: string, rel: string, acc: string[]): void {
  for (const ent of fs.readdirSync(dir)) {
    const full = path.join(dir, ent);
    const r = rel === "" ? ent : rel + "/" + ent;
    const st = fs.statSync(full);
    if (st.isDirectory()) walk(full, r, acc);
    else if (st.isFile()) acc.push(r);
  }
}

function run(argv: string[], io: IO): number {
  const usageErr = (m: string): number => {
    io.err(USAGE + `sitegen: error: ${m}\n`);
    return 2;
  };
  if (argv.length === 0) return usageErr("a command is required");
  const [cmd, ...rest] = argv;
  if (cmd === "-h" || cmd === "--help") {
    io.out(USAGE);
    return 0;
  }
  if (cmd.startsWith("-")) return usageErr(`unrecognized option: ${cmd}`);
  if (cmd !== "build" && cmd !== "check") return usageErr(`unknown command: ${cmd}`);

  const pos: string[] = [];
  let optionsDone = false;
  for (const a of rest) {
    if (!optionsDone && a === "--") {
      optionsDone = true;
    } else if (!optionsDone && (a === "-h" || a === "--help")) {
      io.out(USAGE);
      return 0;
    } else if (!optionsDone && a.startsWith("-") && a.length > 1) {
      return usageErr(`unrecognized option: ${a}`);
    } else {
      pos.push(a);
    }
  }
  const want = cmd === "build" ? 2 : 1;
  if (pos.length !== want) return usageErr(`wrong number of arguments for ${cmd}`);

  if (cmd === "build") {
    try {
      const r = build(pos[0], pos[1]);
      io.out(
        `built: ${r.posts} posts, ${r.tagPages} tag pages, ${r.staticFiles} static files, ${r.drafts} drafts skipped\n`,
      );
      return 0;
    } catch (e) {
      if (e instanceof SitegenError) {
        io.err(`error: ${e.message}\n`);
        return 1;
      }
      throw e;
    }
  }

  const outDir = pos[0];
  let isDirectory = false;
  try {
    isDirectory = fs.statSync(outDir).isDirectory();
  } catch {
    isDirectory = false;
  }
  if (!isDirectory) {
    io.err(`error: not a directory: ${outDir}\n`);
    return 1;
  }
  const files: string[] = [];
  walk(outDir, "", files);
  const pages: Record<string, string> = {};
  let htmlCount = 0;
  for (const rel of files) {
    const key = "/" + rel;
    if (key.endsWith(".html")) {
      pages[key] = new TextDecoder("utf-8", { fatal: false, ignoreBOM: true }).decode(
        fs.readFileSync(path.join(outDir, ...rel.split("/"))),
      );
      htmlCount++;
    } else {
      pages[key] = "";
    }
  }
  const broken = findBrokenLinks(pages);
  for (const [page, href] of broken) io.out(`broken: ${page} -> ${href}\n`);
  io.out(`checked ${htmlCount} pages, ${broken.length} broken links\n`);
  return broken.length > 0 ? 1 : 0;
}

export function main(argv: string[], io?: IO): number {
  const sink: IO = io ?? {
    out: (t) => void process.stdout.write(t),
    err: (t) => void process.stderr.write(t),
  };
  try {
    return run(argv, sink);
  } catch (e) {
    try {
      sink.err(`error: ${e instanceof Error ? e.message : String(e)}\n`);
    } catch {
      // ignore
    }
    return 1;
  }
}

function isMain(): boolean {
  try {
    const self = fs.realpathSync(fileURLToPath(import.meta.url));
    return process.argv[1] !== undefined && fs.realpathSync(process.argv[1]) === self;
  } catch {
    return false;
  }
}

if (isMain()) {
  process.exitCode = main(process.argv.slice(2));
}
