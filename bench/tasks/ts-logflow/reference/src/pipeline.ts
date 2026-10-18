import { StageError, type Args, type Report, type Transform } from "./types.js";
import { parseAll } from "./parse.js";
import { filter } from "./stages/filter.js";
import { dedupe } from "./stages/dedupe.js";
import { redact } from "./stages/redact.js";
import { count } from "./reports/count.js";
import { percentile } from "./reports/percentile.js";
import { topmsg } from "./reports/topmsg.js";
import { render } from "./render.js";

export interface PipelineSpec {
  stages: string[];
  report?: string;
  format?: string;
}

const TRANSFORMS: Record<string, Transform> = { filter, dedupe, redact };
const REPORTS: Record<string, Report> = { count, percentile, topmsg };

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

export function runPipeline(input: string, spec: PipelineSpec): { code: number; out: string; err: string } {
  try {
    const stages = spec.stages.map((s) => {
      const [name, args] = parseSpec(s);
      if (!Object.hasOwn(TRANSFORMS, name)) throw new StageError(`unknown stage ${name}`);
      return { run: TRANSFORMS[name], args };
    });
    let report: { run: Report; args: Args } | null = null;
    if (spec.report !== undefined) {
      const [name, args] = parseSpec(spec.report);
      if (!Object.hasOwn(REPORTS, name)) throw new StageError(`unknown report ${name}`);
      report = { run: REPORTS[name], args };
    }
    const { records, bad } = parseAll(input);
    let current = records;
    for (const s of stages) current = s.run(current, s.args);
    const out = report ? report.run(current, report.args) : render(current, spec.format ?? "text");
    return { code: 0, out, err: bad > 0 ? `warning: ${bad} unparseable line(s)\n` : "" };
  } catch (e) {
    if (e instanceof StageError) return { code: 2, out: "", err: `error: ${e.message}\n` };
    throw e;
  }
}
