import { StageError, type Args } from "./types.js";
import { parseAll } from "./parse.js";
import { render } from "./render.js";
import { renderTable } from "./render-table.js";
import { defaultRegistry, type Registry } from "./registry.js";

export interface PipelineSpec {
  stages: string[];
  report?: string;
  format?: string;
}

function parseSpec(text: string): [string, Args] {
  const i = text.indexOf(":");
  const name = i < 0 ? text : text.slice(0, i);
  const args: Args = {};
  if (i >= 0 && text.slice(i + 1) !== "") {
    for (const part of text.slice(i + 1).split(",")) {
      const j = part.indexOf("=");
      if (j < 1) throw new StageError(`bad argument: ${part}`);
      args[part.slice(0, j)] = part.slice(j + 1);
    }
  }
  return [name, args];
}

export function runPipeline(
  input: string, spec: PipelineSpec, registry: Registry = defaultRegistry(),
): { code: number; out: string; err: string } {
  try {
    const stages = spec.stages.map((s) => {
      const [name, args] = parseSpec(s);
      const run = registry.getTransform(name);
      if (!run) throw new StageError(`unknown stage ${name}`);
      return { run, args };
    });
    let finish: ((records: import("./types.js").Rec[]) => string) | null = null;
    if (spec.report !== undefined) {
      const [name, args] = parseSpec(spec.report);
      const text = registry.getReport(name);
      const table = registry.getTable(name);
      if (text) finish = (records) => text(records, args);
      else if (table) finish = (records) => renderTable(table(records, args), spec.format ?? "text");
      else throw new StageError(`unknown report ${name}`);
    }
    const { records, bad } = parseAll(input);
    let current = records;
    for (const s of stages) current = s.run(current, s.args);
    const out = finish ? finish(current) : render(current, spec.format ?? "text");
    return { code: 0, out, err: bad > 0 ? `warning: ${bad} unparseable line(s)\n` : "" };
  } catch (e) {
    if (e instanceof StageError) return { code: 2, out: "", err: `error: ${e.message}\n` };
    throw e;
  }
}
