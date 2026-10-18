import { StageError } from "./types.js";

const UNITS: [string, number][] = [["d", 86400000], ["h", 3600000], ["m", 60000], ["s", 1000], ["ms", 1]];

export function parseDuration(text: string): number {
  if (!/^(\d+(ms|d|h|m|s))+$/.test(text)) throw new StageError(`bad duration: ${text}`);
  let total = 0;
  for (const m of text.matchAll(/(\d+)(ms|d|h|m|s)/g)) {
    total += Number(m[1]) * UNITS.find((u) => u[0] === m[2])![1];
  }
  return total;
}

export function formatDuration(ms: number): string {
  if (ms === 0) return "0s";
  let rest = ms;
  let out = "";
  for (const [unit, size] of UNITS) {
    const n = Math.floor(rest / size);
    if (n > 0) {
      out += `${n}${unit}`;
      rest -= n * size;
    }
  }
  return out;
}
