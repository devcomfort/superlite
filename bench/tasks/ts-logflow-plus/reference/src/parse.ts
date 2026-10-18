import { normalizeLevel } from "./levels.js";
import type { Rec } from "./types.js";

const LINE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z \[([A-Za-z]+)\] ([A-Za-z0-9_.-]+):(?: (.*))?$/;
const KV = /[A-Za-z_][A-Za-z0-9_.]*=("(?:[^"\\]|\\.)*"|\S*)/y;
const WORD = /\S+/y;

export function parseLine(line: string): Rec | null {
  const m = LINE.exec(line.replace(/\r$/, ""));
  if (!m) return null;
  const [, Y, Mo, D, h, mi, s, frac, lv, service, rest = ""] = m;
  const level = normalizeLevel(lv);
  if (!level) return null;
  const ms = frac ? Number(frac.slice(0, 3).padEnd(3, "0")) : 0;
  const ts = Date.UTC(+Y, +Mo - 1, +D, +h, +mi, +s, ms);
  const d = new Date(ts);
  if (d.getUTCFullYear() !== +Y || d.getUTCMonth() !== +Mo - 1 || d.getUTCDate() !== +D ||
      d.getUTCHours() !== +h || d.getUTCMinutes() !== +mi || d.getUTCSeconds() !== +s) return null;

  const fields: Record<string, string> = {};
  let msgEnd = -1;
  let ok = true;
  let pos = 0;
  while (pos < rest.length) {
    if (rest[pos] === " ") { pos++; continue; }
    KV.lastIndex = pos;
    const k = KV.exec(rest);
    if (k) {
      if (msgEnd < 0) msgEnd = pos;
      let v = k[1];
      if (v.startsWith('"')) v = v.slice(1, -1).replace(/\\(.)/g, "$1");
      fields[k[0].slice(0, k[0].indexOf("="))] = v;
      pos += k[0].length;
    } else {
      if (msgEnd >= 0) { ok = false; break; }
      WORD.lastIndex = pos;
      pos += WORD.exec(rest)![0].length;
    }
  }
  if (!ok) return { ts, level, service, msg: rest.trim(), fields: {} };
  return { ts, level, service, msg: (msgEnd < 0 ? rest : rest.slice(0, msgEnd)).trim(), fields };
}

export function parseAll(text: string): { records: Rec[]; bad: number } {
  const records: Rec[] = [];
  let bad = 0;
  for (const line of text.split("\n")) {
    if (line.trim() === "") continue;
    const r = parseLine(line);
    if (r) records.push(r);
    else bad++;
  }
  return { records, bad };
}
