import { describe, expect, test } from "vitest";
import { run as wordstat } from "../src/commands/wordstat.js";
import { run as linestat } from "../src/commands/linestat.js";
import { run as csvsum } from "../src/commands/csvsum.js";
import { run as slugify } from "../src/commands/slugify.js";
import { cli } from "./helpers.js";

describe("wordstat", () => {
  test("counts, orders by count desc then word asc", () => {
    expect(wordstat(["--top", "3"], "the cat the dog b a b a the")).toEqual({ code: 0, out: "the 3\na 2\nb 2\n", err: "" });
  });
  test("default top is 10", () => {
    const text = "abcdefghijkl".split("").map((l, i) => `${l}${l} `.repeat(12 - i)).join("");
    expect(wordstat([], text).out.split("\n").filter(Boolean)).toHaveLength(10);
  });
  test("--top=N form and fewer words than N", () => {
    expect(wordstat(["--top=5"], "a a b").out).toBe("a 2\nb 1\n");
  });
  test("unicode lowercased, digits and apostrophes separate", () => {
    expect(wordstat([], "ÉCOLE école don't a1b").out).toBe("école 2\na 1\nb 1\ndon 1\nt 1\n");
  });
  test("no letters prints nothing", () => {
    expect(wordstat([], "123 !!!")).toEqual({ code: 0, out: "", err: "" });
  });
  test.each([["0"], ["-3"], ["abc"], ["2.5"]])("invalid N %s is a usage error", (n) => {
    const r = wordstat(["--top", n], "a");
    expect(r.code).toBe(2);
    expect(r.out).toBe("");
    expect(r.err.startsWith("usage:")).toBe(true);
    expect(r.err.endsWith("\n")).toBe(true);
  });
  test("missing value and unknown argument", () => {
    expect(wordstat(["--top"], "a").code).toBe(2);
    expect(wordstat(["--bogus"], "a").code).toBe(2);
  });
});

describe("linestat", () => {
  test("spec example", () => {
    expect(linestat([], "ab cd\nefg\n").out).toBe("lines 2\nwords 3\nchars 10\nlongest 5\n");
  });
  test("no trailing newline still counts last line", () => {
    expect(linestat([], "a\nbb").out).toBe("lines 2\nwords 2\nchars 4\nlongest 2\n");
  });
  test("empty input", () => {
    expect(linestat([], "").out).toBe("lines 0\nwords 0\nchars 0\nlongest 0\n");
  });
  test("code points, not UTF-16 units", () => {
    expect(linestat([], "😀é\n").out).toBe("lines 1\nwords 1\nchars 3\nlongest 2\n");
  });
  test("blank lines count as lines", () => {
    expect(linestat([], "\n\nx\n").out).toBe("lines 3\nwords 1\nchars 4\nlongest 1\n");
  });
  test("arguments are a usage error", () => {
    const r = linestat(["x"], "a");
    expect(r.code).toBe(2);
    expect(r.out).toBe("");
    expect(r.err.startsWith("usage:")).toBe(true);
  });
});

describe("csvsum", () => {
  test("sums a column", () => {
    expect(csvsum(["--col", "b"], "a,b\n1,2\n3,4\n")).toEqual({ code: 0, out: "6\n", err: "" });
  });
  test("decimals, rounding and --col=NAME", () => {
    expect(csvsum(["--col=x"], "x\n0.1\n0.2\n").out).toBe("0.3\n");
    expect(csvsum(["--col", "x"], "x\n-1.25\n").out).toBe("-1.25\n");
  });
  test("trims cells, skips empty cells, short rows and blank lines, accepts CRLF", () => {
    expect(csvsum(["--col", "b"], "a , b\r\n1, 5 \r\n\r\n2,\r\n3\r\n").out).toBe("5\n");
  });
  test("header only prints 0", () => {
    expect(csvsum(["--col", "a"], "a,b\n").out).toBe("0\n");
  });
  test("non-numeric cell reports the data row", () => {
    const r = csvsum(["--col", "a"], "a\n1\n2\nx\n");
    expect(r).toEqual({ code: 3, out: "", err: "error: row 3: not a number\n" });
  });
  test("unknown column and no header are data errors", () => {
    expect(csvsum(["--col", "z"], "a\n1\n")).toEqual({ code: 3, out: "", err: "error: no such column\n" });
    expect(csvsum(["--col", "a"], "\n\n")).toEqual({ code: 3, out: "", err: "error: no header\n" });
  });
  test("missing --col is a usage error", () => {
    expect(csvsum([], "a\n1\n").code).toBe(2);
    expect(csvsum(["--col"], "a\n1\n").code).toBe(2);
    expect(csvsum(["--nope", "a"], "a\n1\n").err.startsWith("usage:")).toBe(true);
  });
});

describe("slugify", () => {
  test("spec examples", () => {
    expect(slugify([], "Hello, World!\n  --A  b-- \nÜnï cödé 42\n").out).toBe("hello-world\na-b\nünï-cödé-42\n");
  });
  test("line without letters or digits gives an empty line", () => {
    expect(slugify([], "!!!\nx\n").out).toBe("\nx\n");
  });
  test("final newline adds no line; empty input prints nothing", () => {
    expect(slugify([], "a b").out).toBe("a-b\n");
    expect(slugify([], "")).toEqual({ code: 0, out: "", err: "" });
  });
  test("arguments are a usage error", () => {
    expect(slugify(["x"], "a").code).toBe(2);
  });
});

describe("dispatcher", () => {
  test("routes each command", () => {
    expect(cli("a a b", "wordstat", "--top", "1").out).toBe("a 2\n");
    expect(cli("x y\n", "linestat").out).toBe("lines 1\nwords 2\nchars 4\nlongest 3\n");
    expect(cli("n\n2\n3\n", "csvsum", "--col", "n").out).toBe("5\n");
    expect(cli("A B\n", "slugify").out).toBe("a-b\n");
  });
  test("exit codes and streams pass through", () => {
    const bad = cli("a\n1\nz\n", "csvsum", "--col", "a");
    expect(bad.code).toBe(3);
    expect(bad.out).toBe("");
    expect(bad.err).toBe("error: row 2: not a number\n");
    const use = cli("a", "wordstat", "--top", "0");
    expect(use.code).toBe(2);
    expect(use.err.startsWith("usage:")).toBe(true);
  });
  test("no command or unknown command is a usage error listing the commands", () => {
    for (const args of [[], ["nope"]]) {
      const r = cli("", ...args);
      expect(r.code).toBe(2);
      expect(r.out).toBe("");
      expect(r.err.startsWith("usage:")).toBe(true);
      for (const c of ["wordstat", "linestat", "csvsum", "slugify"]) expect(r.err).toContain(c);
    }
  });
  test("--help prints usage to stdout, exit 0", () => {
    const r = cli("", "--help");
    expect(r.code).toBe(0);
    expect(r.out.startsWith("usage:")).toBe(true);
  });
});
