import { StageError, type Plugin, type Report, type TableReport, type Transform } from "./types.js";
import { filter } from "./stages/filter.js";
import { dedupe } from "./stages/dedupe.js";
import { redact } from "./stages/redact.js";
import { normalise } from "./stages/normalise.js";
import { count } from "./reports/count.js";
import { percentile } from "./reports/percentile.js";
import { topmsg } from "./reports/topmsg.js";
import { rollup } from "./reports/rollup.js";

const NAME = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/;
const KEY = /^[a-z][a-z0-9_]*$/;
type Kind = "stage" | "report" | "table";
const KINDS: Kind[] = ["stage", "report", "table"];

export class Registry {
  private stages = new Map<string, Transform>();
  private reports = new Map<string, Report>();
  private tables = new Map<string, TableReport>();

  private taken(name: string): boolean {
    return this.stages.has(name) || this.reports.has(name) || this.tables.has(name);
  }

  private check(name: string): void {
    if (!NAME.test(name)) throw new StageError(`bad name: ${name}`);
    if (this.taken(name)) throw new StageError(`duplicate name: ${name}`);
  }

  addTransform(name: string, fn: Transform): void { this.check(name); this.stages.set(name, fn); }
  addReport(name: string, fn: Report): void { this.check(name); this.reports.set(name, fn); }
  addTable(name: string, fn: TableReport): void { this.check(name); this.tables.set(name, fn); }

  addPlugin(plugin: Plugin): void {
    if (!NAME.test(plugin.name)) throw new StageError(`bad name: ${plugin.name}`);
    const planned: [Kind, string, unknown][] = [];
    const seen = new Set<string>();
    const groups: [Kind, Record<string, unknown> | undefined][] = [
      ["stage", plugin.transforms], ["report", plugin.reports], ["table", plugin.tables],
    ];
    for (const [kind, group] of groups) {
      for (const [key, fn] of Object.entries(group ?? {})) {
        if (!KEY.test(key)) throw new StageError(`bad name: ${key}`);
        const full = `${plugin.name}.${key}`;
        this.check(full);
        if (seen.has(full)) throw new StageError(`duplicate name: ${full}`);
        seen.add(full);
        planned.push([kind, full, fn]);
      }
    }
    for (const [kind, full, fn] of planned) {
      if (kind === "stage") this.stages.set(full, fn as Transform);
      else if (kind === "report") this.reports.set(full, fn as Report);
      else this.tables.set(full, fn as TableReport);
    }
  }

  getTransform(name: string): Transform | undefined { return this.stages.get(name); }
  getReport(name: string): Report | undefined { return this.reports.get(name); }
  getTable(name: string): TableReport | undefined { return this.tables.get(name); }

  list(): string[] {
    const names: Record<Kind, string[]> = {
      stage: [...this.stages.keys()], report: [...this.reports.keys()], table: [...this.tables.keys()],
    };
    return KINDS.flatMap((k) => names[k].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)).map((n) => `${k} ${n}`));
  }
}

export function defaultRegistry(): Registry {
  const r = new Registry();
  r.addTransform("filter", filter);
  r.addTransform("dedupe", dedupe);
  r.addTransform("redact", redact);
  r.addTransform("normalise", normalise);
  r.addReport("count", count);
  r.addReport("percentile", percentile);
  r.addReport("topmsg", topmsg);
  r.addTable("rollup", rollup);
  return r;
}
