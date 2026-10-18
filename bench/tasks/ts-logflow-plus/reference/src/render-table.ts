import { StageError, type Table } from "./types.js";

const cell = (v: string) => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

export function renderTable(table: Table, format: string): string {
  switch (format) {
    case "text":
      return [table.columns, ...table.rows].map((row) => row.join("\t") + "\n").join("");
    case "json":
      return table.rows.map((row) => {
        const obj: Record<string, string> = {};
        table.columns.forEach((c, i) => { obj[c] = row[i] ?? ""; });
        return JSON.stringify(obj) + "\n";
      }).join("");
    case "csv":
      return [table.columns, ...table.rows].map((row) => row.map(cell).join(",") + "\n").join("");
    default:
      throw new StageError(`unknown format: ${format}`);
  }
}
