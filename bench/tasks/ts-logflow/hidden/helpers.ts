import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Rec } from "../src/types.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export function cli(input: string, ...args: string[]) {
  const r = spawnSync("node", ["dist/cli.js", ...args], {
    cwd: root, input, encoding: "utf8", maxBuffer: 64 * 1024 * 1024, timeout: 60000,
  });
  return { code: r.status, out: r.stdout ?? "", err: r.stderr ?? "" };
}

export const T0 = Date.UTC(2024, 2, 5, 10, 0, 0);

/** A record `sec` seconds after T0. */
export function rec(sec: number, level: Rec["level"], service: string, msg: string, fields: Record<string, string> = {}): Rec {
  return { ts: T0 + sec * 1000, level, service, msg, fields };
}
