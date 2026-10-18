import type { Level } from "./types.js";

export const LEVELS: Level[] = ["debug", "info", "warn", "error"];

const RANK: Record<Level, number> = { debug: 10, info: 20, warn: 30, error: 40 };

const ALIASES: Record<string, Level> = {
  trace: "debug", debug: "debug", info: "info", notice: "info", warn: "warn", warning: "warn",
  error: "error", err: "error", fatal: "error", critical: "error",
};

export function normalizeLevel(name: string): Level | null {
  const key = name.toLowerCase();
  return Object.hasOwn(ALIASES, key) ? ALIASES[key] : null;
}

export function levelRank(level: Level): number {
  return RANK[level];
}
