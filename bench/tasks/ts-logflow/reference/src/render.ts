import { StageError, type Rec } from "./types.js";

const iso = (ts: number) => new Date(ts).toISOString();
const sorted = (f: Record<string, string>) => Object.keys(f).sort().map((k) => [k, f[k]] as const);
const quote = (v: string) => (v === "" || /[\s"=\\]/.test(v) ? `"${v.replace(/[\\"]/g, "\\$&")}"` : v);
const cell = (v: string) => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

export function render(records: Rec[], format: string): string {
  switch (format) {
    case "text":
      return records.map((r) => {
        const head = `${iso(r.ts)} [${r.level.toUpperCase()}] ${r.service}:`;
        const kv = sorted(r.fields).map(([k, v]) => ` ${k}=${quote(v)}`).join("");
        return `${head}${r.msg ? " " + r.msg : ""}${kv}\n`;
      }).join("");
    case "json":
      return records.map((r) => JSON.stringify({
        ts: iso(r.ts), level: r.level, service: r.service, msg: r.msg,
        fields: Object.fromEntries(sorted(r.fields)),
      }) + "\n").join("");
    case "csv":
      return "ts,level,service,msg,fields\n" + records.map((r) =>
        [iso(r.ts), r.level, r.service, r.msg, sorted(r.fields).map(([k, v]) => `${k}=${v}`).join(";")]
          .map(cell).join(",") + "\n").join("");
    default:
      throw new StageError(`unknown format: ${format}`);
  }
}
