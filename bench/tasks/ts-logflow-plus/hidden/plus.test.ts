import { describe, expect, test } from "vitest";
import { fmtNumber } from "../src/format.js";
import { SERVICE_ALIASES, canonicalService, normaliseKey } from "../src/aliases.js";
import { normalise } from "../src/stages/normalise.js";
import { rollup } from "../src/reports/rollup.js";
import { renderTable } from "../src/render-table.js";
import { Registry, defaultRegistry } from "../src/registry.js";
import { runPipeline } from "../src/pipeline.js";
import { StageError, type Table } from "../src/types.js";
import { cli, rec } from "./helpers.js";

describe("format", () => {
  test.each([
    [3, "3"], [0.1 + 0.2, "0.3"], [-1.25, "-1.25"], [0.0000001, "0"], [-0.0000001, "0"], [1234.5, "1234.5"], [2 / 3, "0.666667"], [0, "0"],
  ])("fmtNumber(%j) is %j", (x, text) => {
    expect(fmtNumber(x)).toBe(text);
  });
});

describe("aliases", () => {
  test("the alias table", () => {
    expect(SERVICE_ALIASES).toEqual({
      authsvc: "auth", "auth-service": "auth", "api-gw": "api", gateway: "api",
      database: "db", postgres: "db", pg: "db", cache: "redis",
    });
  });
  test("canonicalService lower-cases and maps aliases", () => {
    expect(canonicalService("AuthSvc")).toBe("auth");
    expect(canonicalService("API-GW")).toBe("api");
    expect(canonicalService("PG")).toBe("db");
    expect(canonicalService("Billing")).toBe("billing");
    expect(canonicalService("constructor")).toBe("constructor");
  });
  test("normaliseKey", () => {
    expect(normaliseKey("User.Id")).toBe("user_id");
    expect(normaliseKey("A.b.C")).toBe("a_b_c");
    expect(normaliseKey("plain")).toBe("plain");
  });
});

describe("normalise", () => {
  const r1 = rec(0, "info", "AuthSvc", "  two   spaces\tand tab ", { "User.Id": "7", Trace: "t" });
  test("all switches on by default", () => {
    expect(normalise([r1], {})[0]).toEqual({ ...r1, service: "auth", msg: "two spaces and tab", fields: { user_id: "7", trace: "t" } });
  });
  test("switches are independent", () => {
    expect(normalise([r1], { service: "off" })[0].service).toBe("AuthSvc");
    expect(Object.keys(normalise([r1], { keys: "off" })[0].fields)).toEqual(["User.Id", "Trace"]);
    expect(normalise([r1], { ws: "off" })[0].msg).toBe(r1.msg);
  });
  test("key collisions: the later key wins", () => {
    expect(normalise([rec(0, "info", "a", "m", { "A.b": "1", a_b: "2" })], {})[0].fields).toEqual({ a_b: "2" });
  });
  test("bad arguments raise StageError", () => {
    expect(() => normalise([r1], { colour: "on" })).toThrow(StageError);
    expect(() => normalise([r1], { keys: "yes" })).toThrow(StageError);
  });
  test("input is not modified", () => {
    const before = JSON.stringify(r1);
    normalise([r1], {});
    expect(JSON.stringify(r1)).toBe(before);
  });
});

describe("rollup", () => {
  const recs = [
    rec(0, "info", "api", "a", { latency_ms: "10", status: "200" }),
    rec(30, "warn", "api", "b", { latency_ms: "20" }),
    rec(70, "info", "db", "c", { latency_ms: "x", status: "200" }),
    rec(80, "error", "db", "d", { latency_ms: "5.5" }),
    rec(130, "info", "auth", "e"),
  ];
  test("count by service", () => {
    expect(rollup(recs, { by: "service" })).toEqual({
      columns: ["key", "value", "n"], rows: [["api", "2", "2"], ["auth", "1", "1"], ["db", "2", "2"]],
    });
  });
  test("sum ignores non-numbers and omits empty groups", () => {
    expect(rollup(recs, { by: "service", fn: "sum", field: "latency_ms" }).rows).toEqual([["api", "30", "2"], ["db", "5.5", "1"]]);
  });
  test("avg by minute", () => {
    expect(rollup(recs, { by: "minute", fn: "avg", field: "latency_ms" }).rows)
      .toEqual([["2024-03-05T10:00", "15", "2"], ["2024-03-05T10:01", "5.5", "1"]]);
  });
  test("min and max", () => {
    expect(rollup(recs, { by: "level", fn: "min", field: "latency_ms" }).rows).toEqual([["error", "5.5", "1"], ["info", "10", "1"], ["warn", "20", "1"]]);
    expect(rollup(recs, { by: "service", fn: "max", field: "latency_ms" }).rows).toEqual([["api", "20", "2"], ["db", "5.5", "1"]]);
  });
  test("by field skips records without it", () => {
    expect(rollup(recs, { by: "field:status" }).rows).toEqual([["200", "2", "2"]]);
  });
  test("fn count ignores field; values use fmtNumber", () => {
    expect(rollup(recs, { by: "level", fn: "count", field: "nope" }).rows).toHaveLength(3);
    const f = [rec(0, "info", "a", "m", { v: "0.1" }), rec(1, "info", "a", "m", { v: "0.2" })];
    expect(rollup(f, { by: "service", fn: "sum", field: "v" }).rows).toEqual([["a", "0.3", "2"]]);
    expect(rollup(f, { by: "service", fn: "avg", field: "v" }).rows).toEqual([["a", "0.15", "2"]]);
  });
  test("no records gives columns and no rows", () => {
    expect(rollup([], { by: "level" })).toEqual({ columns: ["key", "value", "n"], rows: [] });
  });
  test.each([
    [{}], [{ by: "bogus" }], [{ by: "field:" }], [{ by: "level", fn: "median", field: "v" }],
    [{ by: "level", fn: "sum" }], [{ by: "level", fn: "avg", field: "" }], [{ by: "level", top: "1" }],
  ])("bad arguments %j raise StageError", (args) => {
    expect(() => rollup(recs, args)).toThrow(StageError);
  });
});

describe("renderTable", () => {
  const table: Table = { columns: ["key", "value", "n"], rows: [["a", "1", "1"], ["b,c", 'say "x"', "2"]] };
  test("text", () => {
    expect(renderTable(table, "text")).toBe('key\tvalue\tn\na\t1\t1\nb,c\tsay "x"\t2\n');
  });
  test("json", () => {
    expect(renderTable(table, "json")).toBe(
      '{"key":"a","value":"1","n":"1"}\n{"key":"b,c","value":"say \\"x\\"","n":"2"}\n');
  });
  test("csv quoting", () => {
    expect(renderTable(table, "csv")).toBe('key,value,n\na,1,1\n"b,c","say ""x""",2\n');
  });
  test("no rows", () => {
    const empty: Table = { columns: ["key", "value"], rows: [] };
    expect(renderTable(empty, "text")).toBe("key\tvalue\n");
    expect(renderTable(empty, "csv")).toBe("key,value\n");
    expect(renderTable(empty, "json")).toBe("");
  });
  test("unknown format", () => {
    expect(() => renderTable(table, "xml")).toThrow("unknown format: xml");
  });
});

describe("registry", () => {
  const id = (r: unknown[]) => r;
  test("defaultRegistry lists the built-ins in order", () => {
    expect(defaultRegistry().list()).toEqual([
      "stage dedupe", "stage filter", "stage normalise", "stage redact",
      "report count", "report percentile", "report topmsg", "table rollup",
    ]);
  });
  test("defaultRegistry returns a fresh registry each time", () => {
    const a = defaultRegistry();
    a.addTransform("extra", id as never);
    expect(defaultRegistry().getTransform("extra")).toBeUndefined();
    expect(a.getTransform("filter")).toBeTypeOf("function");
    expect(a.getReport("count")).toBeTypeOf("function");
    expect(a.getTable("rollup")).toBeTypeOf("function");
  });
  test("add and get each kind; unknown names give nothing", () => {
    const r = new Registry();
    r.addTransform("t", id as never);
    r.addReport("r", (() => "") as never);
    r.addTable("tb", (() => ({ columns: [], rows: [] })) as never);
    expect(r.getTransform("t")).toBe(id);
    expect(r.getReport("t")).toBeUndefined();
    expect(r.getTable("nope")).toBeUndefined();
    expect(r.list()).toEqual(["stage t", "report r", "table tb"]);
  });
  test.each(["", "Bad", "1x", "a..b", "a-b", ".a", "a.", "a b"])("invalid name %j", (name) => {
    expect(() => new Registry().addTransform(name, id as never)).toThrow(`bad name: ${name}`);
  });
  test("valid dotted names", () => {
    const r = new Registry();
    r.addReport("geo.lookup_2", (() => "") as never);
    expect(r.list()).toEqual(["report geo.lookup_2"]);
  });
  test("names are unique across kinds", () => {
    const r = new Registry();
    r.addTransform("x", id as never);
    expect(() => r.addTransform("x", id as never)).toThrow("duplicate name: x");
    expect(() => r.addReport("x", (() => "") as never)).toThrow(StageError);
    expect(() => r.addTable("x", (() => ({ columns: [], rows: [] })) as never)).toThrow(StageError);
  });
  test("plugins register entries under their name", () => {
    const r = new Registry();
    r.addPlugin({ name: "geo", transforms: { tag: id as never }, reports: { total: (() => "") as never } });
    expect(r.getTransform("geo.tag")).toBe(id);
    expect(r.list()).toEqual(["stage geo.tag", "report geo.total"]);
  });
  test("a failing plugin registers nothing", () => {
    const r = new Registry();
    r.addReport("geo.b", (() => "") as never);
    expect(() => r.addPlugin({ name: "geo", transforms: { a: id as never }, reports: { b: (() => "") as never } })).toThrow("duplicate name: geo.b");
    expect(r.getTransform("geo.a")).toBeUndefined();
    expect(r.list()).toEqual(["report geo.b"]);
  });
  test("plugin keys are single parts and the plugin name must be valid", () => {
    const r = new Registry();
    expect(() => r.addPlugin({ name: "geo", transforms: { "a.b": id as never } })).toThrow("bad name: a.b");
    expect(() => r.addPlugin({ name: "Geo", transforms: { a: id as never } })).toThrow(StageError);
    expect(r.list()).toEqual([]);
  });
  test("list sorts each group by name", () => {
    const r = new Registry();
    for (const n of ["b", "a.z", "a"]) r.addTransform(n, id as never);
    r.addTable("k", (() => ({ columns: [], rows: [] })) as never);
    expect(r.list()).toEqual(["stage a", "stage a.z", "stage b", "table k"]);
  });
});

const LOG2 = [
  "2024-03-05T10:00:00Z [info] AuthSvc: login ok latency_ms=10",
  "2024-03-05T10:00:30Z [info] authsvc: login ok latency_ms=30",
  "2024-03-05T10:01:00Z [warn] API-GW: slow latency_ms=100",
].join("\n");
const AVG = "rollup:by=service,fn=avg,field=latency_ms";

describe("pipeline with registry and tables", () => {
  test("normalise then rollup renders a text table", () => {
    const r = runPipeline(LOG2, { stages: ["normalise"], report: AVG });
    expect(r).toEqual({ code: 0, out: "key\tvalue\tn\napi\t100\t1\nauth\t20\t2\n", err: "" });
  });
  test("without normalise the services stay apart, in code-point order", () => {
    expect(runPipeline(LOG2, { stages: [], report: AVG }).out).toBe("key\tvalue\tn\nAPI-GW\t100\t1\nAuthSvc\t10\t1\nauthsvc\t30\t1\n");
  });
  test("format applies to table reports", () => {
    expect(runPipeline(LOG2, { stages: ["normalise"], report: AVG, format: "csv" }).out).toBe("key,value,n\napi,100,1\nauth,20,2\n");
    expect(runPipeline(LOG2, { stages: ["normalise"], report: AVG, format: "json" }).out)
      .toBe('{"key":"api","value":"100","n":"1"}\n{"key":"auth","value":"20","n":"2"}\n');
  });
  test("format is ignored by plain reports", () => {
    expect(runPipeline(LOG2, { stages: [], report: "count:by=level", format: "json" }).out).toBe("info 2\nwarn 1\n");
  });
  test("a bad format fails for tables too", () => {
    expect(runPipeline(LOG2, { stages: [], report: AVG, format: "xml" })).toEqual({ code: 2, out: "", err: "error: unknown format: xml\n" });
  });
  test("table report argument errors give code 2", () => {
    const r = runPipeline(LOG2, { stages: [], report: "rollup:by=service,fn=sum" });
    expect(r.code).toBe(2);
    expect(r.out).toBe("");
    expect(r.err.startsWith("error: ")).toBe(true);
  });
  test("a custom registry's plugin stage, report and table", () => {
    const reg = defaultRegistry();
    reg.addPlugin({
      name: "geo",
      transforms: { upper: (rs) => rs.map((x) => ({ ...x, msg: x.msg.toUpperCase() })) },
      reports: { total: (rs) => `${rs.length}\n` },
      tables: { ends: (rs) => ({ columns: ["first", "last"], rows: [[rs[0].msg, rs[rs.length - 1].msg]] }) },
    });
    expect(runPipeline(LOG2, { stages: ["geo.upper"], report: "geo.total" }, reg).out).toBe("3\n");
    expect(runPipeline(LOG2, { stages: ["geo.upper"], report: "geo.ends" }, reg).out).toBe("first\tlast\nLOGIN OK\tSLOW\n");
    expect(runPipeline(LOG2, { stages: ["geo.upper"], format: "csv" }, reg).out.split("\n")[1]).toContain("LOGIN OK");
  });
  test("plugin names are unknown with the default registry", () => {
    expect(runPipeline(LOG2, { stages: ["geo.upper"] })).toEqual({ code: 2, out: "", err: "error: unknown stage geo.upper\n" });
    expect(runPipeline(LOG2, { stages: [], report: "geo.total" }).err).toBe("error: unknown report geo.total\n");
  });
  test("a table report cannot be used as a stage", () => {
    expect(runPipeline(LOG2, { stages: ["rollup:by=level"] }).err).toBe("error: unknown stage rollup\n");
  });
});

describe("cli list and rollup", () => {
  test("--list prints the registry and reads no input", () => {
    const r = cli("", "--list");
    expect(r.code).toBe(0);
    expect(r.out).toBe("stage dedupe\nstage filter\nstage normalise\nstage redact\nreport count\nreport percentile\nreport topmsg\ntable rollup\n");
    expect(r.err).toBe("");
  });
  test("--list with an unknown option is a usage error", () => {
    const r = cli("", "--list", "--bogus");
    expect(r.code).toBe(2);
    expect(r.err.startsWith("usage:")).toBe(true);
  });
  test("rollup through the CLI", () => {
    const r = cli(LOG2, "--stage", "normalise", "--report", AVG, "--format", "csv");
    expect(r.code).toBe(0);
    expect(r.out).toBe("key,value,n\napi,100,1\nauth,20,2\n");
  });
  test("rollup argument errors exit 2", () => {
    const r = cli(LOG2, "--report", "rollup");
    expect(r.code).toBe(2);
    expect(r.err.startsWith("error: ")).toBe(true);
  });
});
