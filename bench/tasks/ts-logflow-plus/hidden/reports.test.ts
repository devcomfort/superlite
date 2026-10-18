import { describe, expect, test } from "vitest";
import { count } from "../src/reports/count.js";
import { percentile } from "../src/reports/percentile.js";
import { topmsg } from "../src/reports/topmsg.js";
import { render } from "../src/render.js";
import { StageError } from "../src/types.js";
import { rec } from "./helpers.js";

describe("count", () => {
  const recs = [
    rec(0, "info", "api", "a", { status: "200" }),
    rec(30, "warn", "api", "b", { status: "404" }),
    rec(70, "info", "db", "c", { status: "200" }),
    rec(80, "info", "api", "d"),
    rec(130, "error", "auth", "e", { status: "200" }),
  ];
  test("by service, count desc then key asc", () => {
    expect(count(recs, { by: "service" })).toBe("api 3\nauth 1\ndb 1\n");
  });
  test("by level", () => {
    expect(count(recs, { by: "level" })).toBe("info 3\nerror 1\nwarn 1\n");
  });
  test("by minute (UTC) and limit", () => {
    expect(count(recs, { by: "minute" })).toBe("2024-03-05T10:00 2\n2024-03-05T10:01 2\n2024-03-05T10:02 1\n");
    expect(count(recs, { by: "minute", limit: "1" })).toBe("2024-03-05T10:00 2\n");
  });
  test("by field skips records without it", () => {
    expect(count(recs, { by: "field:status" })).toBe("200 3\n404 1\n");
  });
  test("no records prints nothing", () => {
    expect(count([], { by: "level" })).toBe("");
  });
  test.each([[{}], [{ by: "bogus" }], [{ by: "field:" }], [{ by: "level", limit: "0" }], [{ by: "level", limit: "x" }], [{ by: "level", top: "1" }]])(
    "bad arguments %j raise StageError", (args) => {
      expect(() => count(recs, args)).toThrow(StageError);
    });
});

describe("percentile", () => {
  const ten = Array.from({ length: 10 }, (_, i) => rec(i, "info", "a", "m", { v: String(i + 1) }));
  test("defaults use nearest rank", () => {
    expect(percentile(ten, { field: "v" })).toBe("all n=10 p50=5 p90=9 p99=10\n");
  });
  test("custom p written as given, ends and fractions", () => {
    expect(percentile(ten, { field: "v", p: "0,25,100" })).toBe("all n=10 p0=1 p25=3 p100=10\n");
    expect(percentile(ten, { field: "v", p: "99.5" })).toBe("all n=10 p99.5=10\n");
  });
  test("by service, groups ascending, decimals printed plainly", () => {
    const recs = [
      rec(0, "info", "b", "m", { v: "10" }), rec(1, "info", "a", "m", { v: "2.5" }), rec(2, "info", "b", "m", { v: "20" }),
      rec(3, "info", "a", "m", { v: "1" }), rec(4, "info", "a", "m", { v: "3" }), rec(5, "info", "a", "m", { v: "4" }),
    ];
    expect(percentile(recs, { field: "v", by: "service", p: "50,90" })).toBe("a n=4 p50=2.5 p90=4\nb n=2 p50=10 p90=20\n");
  });
  test("ignores non-numeric values, trims, no data prints nothing", () => {
    const recs = [rec(0, "info", "a", "m", { v: "x" }), rec(1, "info", "a", "m", { v: "" }), rec(2, "info", "a", "m", { v: "1e3" }),
      rec(3, "info", "a", "m", { v: " 5 " }), rec(4, "info", "a", "m")];
    expect(percentile(recs, { field: "v", p: "50" })).toBe("all n=1 p50=5\n");
    expect(percentile(recs, { field: "nope" })).toBe("");
  });
  test.each([[{}], [{ field: "" }], [{ field: "v", p: "101" }], [{ field: "v", p: "abc" }], [{ field: "v", by: "level" }], [{ field: "v", q: "1" }]])(
    "bad arguments %j raise StageError", (args) => {
      expect(() => percentile(ten, args)).toThrow(StageError);
    });
});

describe("topmsg", () => {
  const recs = [
    rec(0, "info", "a", "GET /item/12 failed"), rec(1, "info", "a", "GET /item/7 failed"),
    rec(2, "info", "a", "conn 0xff lost"), rec(3, "info", "a", "conn 0xAB lost"),
    rec(4, "info", "a", "took 1.5s"), rec(5, "info", "a", "disk full"), rec(6, "info", "a", "0x1F2 and 33"),
  ];
  test("templates, count desc then template asc", () => {
    expect(topmsg(recs, {})).toBe("2 GET /item/<n> failed\n2 conn <hex> lost\n1 <hex> and <n>\n1 disk full\n1 took <n>s\n");
  });
  test("n limits", () => {
    expect(topmsg(recs, { n: "1" })).toBe("2 GET /item/<n> failed\n");
  });
  test.each([[{ n: "0" }], [{ n: "x" }], [{ top: "1" }]])("bad arguments %j raise StageError", (args) => {
    expect(() => topmsg(recs, args)).toThrow(StageError);
  });
});

describe("render", () => {
  const r1 = rec(1.5, "warn", "auth", "login failed", { user: "bob smith", ip: "1.2.3.4", empty: "" });
  test("text", () => {
    expect(render([r1], "text")).toBe('2024-03-05T10:00:01.500Z [WARN] auth: login failed empty="" ip=1.2.3.4 user="bob smith"\n');
  });
  test("text quoting and empty message", () => {
    expect(render([rec(0, "info", "svc", "", { a: "1" })], "text")).toBe("2024-03-05T10:00:00.000Z [INFO] svc: a=1\n");
    expect(render([rec(0, "info", "svc", "m", { q: 'a"b', e: "x=y", s: "p\\q" })], "text"))
      .toBe('2024-03-05T10:00:00.000Z [INFO] svc: m e="x=y" q="a\\"b" s="p\\\\q"\n');
  });
  test("json keeps key order", () => {
    expect(render([r1], "json")).toBe(
      '{"ts":"2024-03-05T10:00:01.500Z","level":"warn","service":"auth","msg":"login failed","fields":{"empty":"","ip":"1.2.3.4","user":"bob smith"}}\n');
  });
  test("csv with header, ; joined fields and quoting", () => {
    expect(render([r1, rec(0, "info", "s", 'say "x", ok')], "csv")).toBe(
      'ts,level,service,msg,fields\n2024-03-05T10:00:01.500Z,warn,auth,login failed,empty=;ip=1.2.3.4;user=bob smith\n' +
      '2024-03-05T10:00:00.000Z,info,s,"say ""x"", ok",\n');
  });
  test("no records, unknown format", () => {
    expect(render([], "text")).toBe("");
    expect(render([], "json")).toBe("");
    expect(render([], "csv")).toBe("ts,level,service,msg,fields\n");
    expect(() => render([r1], "xml")).toThrow("unknown format: xml");
  });
});
