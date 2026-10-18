import { describe, expect, test } from "vitest";
import { filter } from "../src/stages/filter.js";
import { dedupe } from "../src/stages/dedupe.js";
import { redact } from "../src/stages/redact.js";
import { StageError } from "../src/types.js";
import { T0, rec } from "./helpers.js";

const sample = [
  rec(0, "debug", "auth", "start"),
  rec(10, "info", "api", "GET /a", { status: "200" }),
  rec(20, "warn", "auth", "slow login"),
  rec(30, "error", "api-v2", "crash", { status: "500" }),
  rec(40, "info", "db", "ok"),
];

describe("filter", () => {
  test("level keeps that rank and above, aliases accepted", () => {
    expect(filter(sample, { level: "warn" }).map((r) => r.msg)).toEqual(["slow login", "crash"]);
    expect(filter(sample, { level: "WARNING" })).toHaveLength(2);
  });
  test("service globs and alternatives", () => {
    expect(filter(sample, { service: "api*" }).map((r) => r.service)).toEqual(["api", "api-v2"]);
    expect(filter(sample, { service: "auth,db" })).toHaveLength(3);
    expect(filter(sample, { service: "ap" })).toHaveLength(0);
    expect(filter(sample, { service: "a.i" })).toHaveLength(0);
  });
  test("since and until relative to the latest record, and absolute", () => {
    expect(filter(sample, { since: "20s" }).map((r) => r.msg)).toEqual(["slow login", "crash", "ok"]);
    expect(filter(sample, { until: "20s" }).map((r) => r.msg)).toEqual(["start", "GET /a"]);
    expect(filter(sample, { since: `@${T0 + 10000}`, until: `@${T0 + 30000}` }).map((r) => r.msg)).toEqual(["GET /a", "slow login"]);
  });
  test("grep is a case-sensitive substring; field matches exactly", () => {
    expect(filter(sample, { grep: "GET" })).toHaveLength(1);
    expect(filter(sample, { grep: "get" })).toHaveLength(0);
    expect(filter(sample, { field: "status=500" }).map((r) => r.msg)).toEqual(["crash"]);
  });
  test("criteria combine with AND and input is untouched", () => {
    const before = JSON.stringify(sample);
    expect(filter(sample, { level: "info", service: "api*", field: "status=200" })).toHaveLength(1);
    expect(JSON.stringify(sample)).toBe(before);
  });
  test("bad arguments raise StageError", () => {
    expect(() => filter(sample, { colour: "red" })).toThrow("filter: unknown argument colour");
    expect(() => filter(sample, { level: "loud" })).toThrow(StageError);
    expect(() => filter(sample, { since: "soon" })).toThrow(StageError);
    expect(() => filter(sample, { field: "status" })).toThrow(StageError);
    expect(() => filter(sample, { field: "=x" })).toThrow(StageError);
  });
});

describe("dedupe", () => {
  const dup = [
    rec(0, "error", "api", "boom"),
    rec(2, "error", "api", "boom"),
    rec(4, "error", "api", "other"),
    rec(5, "error", "api", "boom"),
    rec(6, "error", "api", "boom"),
    rec(30, "error", "api", "boom"),
  ];
  test("merges repeats within the window measured from the first", () => {
    const out = dedupe(dup, {});
    expect(out.map((r) => [(r.ts - T0) / 1000, r.msg, r.fields.repeat])).toEqual([
      [0, "boom", "3"], [4, "other", undefined], [6, "boom", undefined], [30, "boom", undefined],
    ]);
  });
  test("custom window", () => {
    const out = dedupe(dup, { window: "1s" });
    expect(out.map((r) => r.fields.repeat)).toEqual([undefined, undefined, undefined, "2", undefined]);
    const wide = dedupe(dup, { window: "1m" });
    expect(wide.map((r) => r.fields.repeat)).toEqual(["5", undefined]);
  });
  test("different service or level never merge; fields kept", () => {
    const out = dedupe([rec(0, "info", "a", "x", { k: "1" }), rec(1, "info", "b", "x"), rec(1, "warn", "a", "x"), rec(2, "info", "a", "x")], {});
    expect(out).toHaveLength(3);
    expect(out[0].fields).toEqual({ k: "1", repeat: "2" });
  });
  test("does not mutate input; bad arguments raise", () => {
    const before = JSON.stringify(dup);
    dedupe(dup, {});
    expect(JSON.stringify(dup)).toBe(before);
    expect(() => dedupe(dup, { window: "x" })).toThrow(StageError);
    expect(() => dedupe(dup, { size: "1" })).toThrow(StageError);
  });
});

describe("redact", () => {
  const r1 = rec(0, "info", "auth", "mail bob@example.com from 10.1.2.3 password=hunter2 ok", {
    token: "abc", Authorization: "Bearer x", ip: "192.168.0.7", note: "plain", user: "a.b@c.org",
  });
  test("all rules by default", () => {
    const [o] = redact([r1], {});
    expect(o.msg).toBe("mail *** from 10.*.*.* password=*** ok");
    expect(o.fields).toEqual({ token: "***", Authorization: "***", ip: "192.*.*.*", note: "plain", user: "***" });
  });
  test("rule subset and custom mask", () => {
    const [o] = redact([r1], { rules: "email", mask: "[x]" });
    expect(o.msg).toBe("mail [x] from 10.1.2.3 password=hunter2 ok");
    expect(o.fields.token).toBe("abc");
    expect(o.fields.user).toBe("[x]");
  });
  test("ip boundaries", () => {
    const [o] = redact([rec(0, "info", "a", "v 999.1.1.1 x 1.2.3.4. y 12.34.56.78.90 z 8.8.8.8")], { rules: "ip" });
    expect(o.msg).toBe("v 999.1.1.1 x 1.*.*.*. y 12.*.*.*.90 z 8.*.*.*");
  });
  test("secret in message is case-insensitive and keeps the key", () => {
    const [o] = redact([rec(0, "info", "a", "Token=abc API_KEY=zzz done")], { rules: "secret" });
    expect(o.msg).toBe("Token=*** API_KEY=*** done");
  });
  test("keys and service untouched; input not mutated; bad args raise", () => {
    const [o] = redact([rec(0, "info", "me@x.com", "m", { "a@b.co": "v" })], {});
    expect(o.service).toBe("me@x.com");
    expect(Object.keys(o.fields)).toEqual(["a@b.co"]);
    const before = JSON.stringify(r1);
    redact([r1], {});
    expect(JSON.stringify(r1)).toBe(before);
    expect(() => redact([r1], { rules: "email,dns" })).toThrow(StageError);
    expect(() => redact([r1], { colour: "x" })).toThrow(StageError);
  });
});
