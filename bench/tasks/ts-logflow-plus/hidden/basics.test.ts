import { describe, expect, test } from "vitest";
import { LEVELS, levelRank, normalizeLevel } from "../src/levels.js";
import { formatDuration, parseDuration } from "../src/duration.js";
import { parseAll, parseLine } from "../src/parse.js";
import { StageError } from "../src/types.js";

describe("levels", () => {
  test("LEVELS order and ranks", () => {
    expect(LEVELS).toEqual(["debug", "info", "warn", "error"]);
    expect(LEVELS.map(levelRank)).toEqual([10, 20, 30, 40]);
  });
  test("aliases and case", () => {
    expect(normalizeLevel("WARNING")).toBe("warn");
    expect(normalizeLevel("Trace")).toBe("debug");
    expect(normalizeLevel("notice")).toBe("info");
    expect(["err", "fatal", "CRITICAL"].map(normalizeLevel)).toEqual(["error", "error", "error"]);
  });
  test("unknown is null", () => {
    expect(normalizeLevel("loud")).toBeNull();
    expect(normalizeLevel("")).toBeNull();
    expect(normalizeLevel("constructor")).toBeNull();
  });
});

describe("duration", () => {
  test("parses single and combined parts", () => {
    expect(parseDuration("250ms")).toBe(250);
    expect(parseDuration("90s")).toBe(90000);
    expect(parseDuration("1h30m")).toBe(5400000);
    expect(parseDuration("1d2h3m4s5ms")).toBe(86400000 + 7200000 + 180000 + 4000 + 5);
    expect(parseDuration("0s")).toBe(0);
  });
  test.each(["", "5", "5x", "1.5h", "-1m", "m5", "1h 30m", "1m5"])("rejects %j", (text) => {
    expect(() => parseDuration(text)).toThrow(StageError);
  });
  test("error message", () => {
    expect(() => parseDuration("5x")).toThrow("bad duration: 5x");
  });
  test("formats", () => {
    expect(formatDuration(5400000)).toBe("1h30m");
    expect(formatDuration(1500)).toBe("1s500ms");
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(86400000 + 60000)).toBe("1d1m");
  });
});

describe("parse", () => {
  test("basic line", () => {
    expect(parseLine("2024-03-05T10:15:30Z [WARN] auth: login failed")).toEqual({
      ts: Date.UTC(2024, 2, 5, 10, 15, 30), level: "warn", service: "auth", msg: "login failed", fields: {},
    });
  });
  test("fraction is truncated to milliseconds", () => {
    expect(parseLine("2024-03-05T10:15:30.1239Z [info] a: x")!.ts).toBe(Date.UTC(2024, 2, 5, 10, 15, 30, 123));
    expect(parseLine("2024-03-05T10:15:30.5Z [info] a: x")!.ts).toBe(Date.UTC(2024, 2, 5, 10, 15, 30, 500));
  });
  test("fields after the message", () => {
    const r = parseLine('2024-03-05T10:15:30Z [info] api: GET /x took 5ms status=200 user="bob smith" note="say \\"hi\\"" empty=')!;
    expect(r.msg).toBe("GET /x took 5ms");
    expect(r.fields).toEqual({ status: "200", user: "bob smith", note: 'say "hi"', empty: "" });
  });
  test("repeated key keeps the last value; message may be empty", () => {
    const r = parseLine("2024-03-05T10:15:30Z [info] api: a=1 a=2")!;
    expect(r.msg).toBe("");
    expect(r.fields).toEqual({ a: "2" });
  });
  test("a non-field token after a field means no fields", () => {
    const r = parseLine("2024-03-05T10:15:30Z [info] api: got a=1 then more")!;
    expect(r.msg).toBe("got a=1 then more");
    expect(r.fields).toEqual({});
  });
  test("empty rest, CRLF, level case", () => {
    expect(parseLine("2024-03-05T10:15:30Z [Error] svc:")!.msg).toBe("");
    expect(parseLine("2024-03-05T10:15:30Z [err] svc: boom\r")!.level).toBe("error");
  });
  test.each([
    "2024-13-05T10:15:30Z [info] a: x",
    "2024-02-30T10:15:30Z [info] a: x",
    "2024-03-05T10:15:60Z [info] a: x",
    "2024-03-05T10:15:30 [info] a: x",
    "2024-03-05T10:15:30Z [loud] a: x",
    "2024-03-05T10:15:30Z [info] bad service: x",
    "2024-03-05T10:15:30Z info a: x",
    "garbage",
  ])("rejects %j", (line) => {
    expect(parseLine(line)).toBeNull();
  });
  test("parseAll skips blank lines, counts bad ones", () => {
    const r = parseAll("2024-03-05T10:15:30Z [info] a: x\n\n   \nnope\n2024-03-05T10:15:31Z [warn] b: y");
    expect(r.records.map((x) => x.service)).toEqual(["a", "b"]);
    expect(r.bad).toBe(1);
  });
});
