import { FrontmatterError } from "./errors.js";
import { setOwn } from "./util.js";

export type Value = null | boolean | number | string | Value[] | { [key: string]: Value };

const LINE = /^([A-Za-z_][A-Za-z0-9_-]*):(?: +([^\n]*))?$/;
const INT = /^[+-]?[0-9]+$/;
const ESC: Record<string, string> = { '"': '"', "\\": "\\", n: "\n", t: "\t" };

function dq(s: string, start: number): [string, number] {
  let out = "";
  let i = start + 1;
  const n = s.length;
  while (i < n) {
    const c = s[i];
    if (c === "\\") {
      if (i + 1 >= n) throw new FrontmatterError("unterminated string");
      const nxt = s[i + 1];
      if (!Object.hasOwn(ESC, nxt)) throw new FrontmatterError(`invalid escape: \\${nxt}`);
      out += ESC[nxt];
      i += 2;
    } else if (c === '"') {
      return [out, i + 1];
    } else {
      out += c;
      i += 1;
    }
  }
  throw new FrontmatterError("unterminated string");
}

function sq(s: string, start: number): [string, number] {
  let out = "";
  let i = start + 1;
  const n = s.length;
  while (i < n) {
    const c = s[i];
    if (c === "'") {
      if (i + 1 < n && s[i + 1] === "'") {
        out += "'";
        i += 2;
      } else {
        return [out, i + 1];
      }
    } else {
      out += c;
      i += 1;
    }
  }
  throw new FrontmatterError("unterminated string");
}

function scalar(v: string): Value {
  if (v === "true") return true;
  if (v === "false") return false;
  if (INT.test(v)) return Number(v) + 0;
  return v;
}

function list(v: string): Value[] {
  if (!v.endsWith("]") || v.length < 2) throw new FrontmatterError("unterminated list");
  const inner = v.slice(1, -1);
  if (inner.trim() === "") return [];
  const items: Value[] = [];
  let i = 0;
  const n = inner.length;
  for (;;) {
    while (i < n && /\s/.test(inner[i])) i++;
    if (i >= n) throw new FrontmatterError("empty list item");
    const c = inner[i];
    let val: Value;
    if (c === '"' || c === "'") {
      let end: number;
      [val, end] = c === '"' ? dq(inner, i) : sq(inner, i);
      i = end;
      while (i < n && /\s/.test(inner[i])) i++;
      if (i < n && inner[i] !== ",") throw new FrontmatterError("unexpected text after quoted item");
    } else {
      let j = inner.indexOf(",", i);
      if (j === -1) j = n;
      const raw = inner.slice(i, j).trim();
      if (raw === "") throw new FrontmatterError("empty list item");
      if (raw.includes("[")) throw new FrontmatterError("nested list");
      val = scalar(raw);
      i = j;
    }
    items.push(val);
    if (i >= n) break;
    i += 1;
  }
  return items;
}

function value(raw: string): Value {
  const v = raw.trim();
  if (v === "") return "";
  if (v[0] === '"') {
    const [val, end] = dq(v, 0);
    if (end !== v.length) throw new FrontmatterError("unexpected text after string");
    return val;
  }
  if (v[0] === "'") {
    const [val, end] = sq(v, 0);
    if (end !== v.length) throw new FrontmatterError("unexpected text after string");
    return val;
  }
  if (v[0] === "[") return list(v);
  return scalar(v);
}

export function parse(text: string): { meta: Record<string, Value>; body: string } {
  text = text.replaceAll("\r\n", "\n");
  const lines = text.split("\n");
  if (lines[0] !== "---") return { meta: {}, body: text };
  let end = -1;
  for (let idx = 1; idx < lines.length; idx++) {
    if (lines[idx] === "---") {
      end = idx;
      break;
    }
  }
  if (end === -1) throw new FrontmatterError("unterminated front matter");
  const meta: Record<string, Value> = {};
  for (const line of lines.slice(1, end)) {
    const stripped = line.trim();
    if (stripped === "" || stripped.startsWith("#")) continue;
    const m = LINE.exec(line);
    if (!m) throw new FrontmatterError(`invalid front matter line: ${JSON.stringify(line)}`);
    const key = m[1];
    if (Object.hasOwn(meta, key)) throw new FrontmatterError(`duplicate key: ${key}`);
    setOwn(meta, key, value(m[2] ?? ""));
  }
  return { meta, body: lines.slice(end + 1).join("\n") };
}
