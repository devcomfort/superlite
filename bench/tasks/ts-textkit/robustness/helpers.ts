import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export function cli(input: string, ...args: string[]) {
  const r = spawnSync("node", ["dist/cli.js", ...args], {
    cwd: root, input, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, timeout: 60000,
  });
  return { code: r.status, out: r.stdout ?? "", err: r.stderr ?? "" };
}
