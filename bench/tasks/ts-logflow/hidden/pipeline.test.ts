import { describe, expect, test } from "vitest";
import { runPipeline } from "../src/pipeline.js";
import { cli } from "./helpers.js";

const LOG = [
  "2024-03-05T10:00:00Z [info] api: GET /a latency_ms=10",
  "2024-03-05T10:00:01Z [warn] auth: login failed user=bob ip=10.1.2.3",
  "2024-03-05T10:00:02Z [error] api: crash code=500 latency_ms=90",
  "garbage line",
  "2024-03-05T10:00:03Z [error] api: crash code=500 latency_ms=70",
  "",
].join("\n");

describe("pipeline", () => {
  test("no stages renders every record as text and warns about bad lines", () => {
    const r = runPipeline(LOG, { stages: [] });
    expect(r.code).toBe(0);
    expect(r.out.split("\n").filter(Boolean)).toHaveLength(4);
    expect(r.out.startsWith("2024-03-05T10:00:00.000Z [INFO] api: GET /a latency_ms=10\n")).toBe(true);
    expect(r.err).toBe("warning: 1 unparseable line(s)\n");
  });
  test("stages chain in order: filter then dedupe", () => {
    const r = runPipeline(LOG, { stages: ["filter:level=error", "dedupe:window=5s"] });
    expect(r.out).toBe("2024-03-05T10:00:02.000Z [ERROR] api: crash code=500 latency_ms=90 repeat=2\n");
  });
  test("filter then redact", () => {
    const r = runPipeline(LOG, { stages: ["filter:service=auth", "redact"] });
    expect(r.out).toBe("2024-03-05T10:00:01.000Z [WARN] auth: login failed ip=10.*.*.* user=bob\n");
  });
  test("report replaces the rendered records; format is then ignored", () => {
    expect(runPipeline(LOG, { stages: [], report: "count:by=service", format: "json" }).out).toBe("api 3\nauth 1\n");
    expect(runPipeline(LOG, { stages: ["filter:level=error"], report: "percentile:field=latency_ms,p=50,by=service" }).out)
      .toBe("api n=2 p50=70\n");
  });
  test("format json", () => {
    const r = runPipeline(LOG, { stages: ["filter:level=warn,service=auth"], format: "json" });
    expect(JSON.parse(r.out).fields).toEqual({ ip: "10.1.2.3", user: "bob" });
  });
  test("argument values keep '=' and ':'", () => {
    const r = runPipeline("2024-03-05T10:00:00Z [info] s: sum a=b done\n", { stages: ["filter:grep=a=b"] });
    expect(r.out).toBe("2024-03-05T10:00:00.000Z [INFO] s: sum a=b done\n");
  });
  test("empty input", () => {
    expect(runPipeline("", { stages: [] })).toEqual({ code: 0, out: "", err: "" });
  });
  test.each([
    [{ stages: ["nope"] }, "error: unknown stage nope\n"],
    [{ stages: ["count:by=level"] }, "error: unknown stage count\n"],
    [{ stages: [], report: "filter" }, "error: unknown report filter\n"],
    [{ stages: ["filter:level"] }, "error: bad argument: level\n"],
    [{ stages: ["filter:=x"] }, "error: bad argument: =x\n"],
    [{ stages: ["filter:colour=red"] }, "error: filter: unknown argument colour\n"],
    [{ stages: [], format: "xml" }, "error: unknown format: xml\n"],
    [{ stages: ["dedupe:window=soon"] }, "error: bad duration: soon\n"],
  ])("StageError %j gives code 2 and an error line", (spec, err) => {
    const r = runPipeline(LOG, spec);
    expect(r).toEqual({ code: 2, out: "", err });
  });
  test("bad specs are reported even when the input is garbage", () => {
    expect(runPipeline("garbage\n", { stages: ["nope"] }).code).toBe(2);
  });
  test("a report error still fails after good stages", () => {
    const r = runPipeline(LOG, { stages: ["filter:level=info"], report: "count" });
    expect(r.code).toBe(2);
    expect(r.err.startsWith("error: ")).toBe(true);
    expect(r.out).toBe("");
  });
});

describe("cli", () => {
  test("stages, report, separate and = forms", () => {
    expect(cli(LOG, "--stage", "filter:level=error", "--report", "count:by=service").out).toBe("api 2\n");
    const r = cli(LOG, "--stage=filter:service=auth", "--format=json");
    expect(r.code).toBe(0);
    expect(JSON.parse(r.out).service).toBe("auth");
  });
  test("several --stage options run in order", () => {
    const r = cli(LOG, "--stage", "filter:level=error", "--stage", "dedupe");
    expect(r.out).toBe("2024-03-05T10:00:02.000Z [ERROR] api: crash code=500 latency_ms=90 repeat=2\n");
  });
  test("warning goes to stderr with exit 0", () => {
    const r = cli(LOG);
    expect(r.code).toBe(0);
    expect(r.err).toBe("warning: 1 unparseable line(s)\n");
  });
  test("stage errors exit 2 with error line on stderr", () => {
    const r = cli(LOG, "--stage", "nope");
    expect(r.code).toBe(2);
    expect(r.out).toBe("");
    expect(r.err).toBe("error: unknown stage nope\n");
  });
  test.each([[["--bogus"]], [["--stage"]], [["--report"]], [["--format"]], [["filter"]]])("usage error %j", (args) => {
    const r = cli(LOG, ...args);
    expect(r.code).toBe(2);
    expect(r.out).toBe("");
    expect(r.err.startsWith("usage:")).toBe(true);
  });
});
