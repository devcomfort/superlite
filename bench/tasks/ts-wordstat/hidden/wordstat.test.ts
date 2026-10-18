import { describe, expect, test } from "vitest";
import { tokenize } from "../src/tokenize.js";
import { countWords } from "../src/count.js";
import { topN } from "../src/topn.js";
import { cli } from "./helpers.js";

describe("tokenize", () => {
  test("lowercases and splits on whitespace", () => {
    expect(tokenize("Hello World")).toEqual(["hello", "world"]);
  });
  test("punctuation, digits, apostrophes and hyphens separate", () => {
    expect(tokenize("don't a1b well-known, ok!")).toEqual(["don", "t", "a", "b", "well", "known", "ok"]);
  });
  test("no empty tokens", () => {
    expect(tokenize("  ,, 12 ;; ")).toEqual([]);
    expect(tokenize("")).toEqual([]);
  });
  test("unicode letters are kept and lowercased", () => {
    expect(tokenize("ÉCOLE straße Жук 日本語")).toEqual(["école", "straße", "жук", "日本語"]);
  });
  test("order of appearance and repeats preserved", () => {
    expect(tokenize("b a b")).toEqual(["b", "a", "b"]);
  });
});

describe("countWords", () => {
  test("counts occurrences", () => {
    const m = countWords(["a", "b", "a"]);
    expect(m.get("a")).toBe(2);
    expect(m.get("b")).toBe(1);
    expect(m.size).toBe(2);
  });
  test("empty gives empty map", () => {
    expect(countWords([]).size).toBe(0);
  });
  test("does not modify input", () => {
    const t = ["x", "y", "x"];
    countWords(t);
    expect(t).toEqual(["x", "y", "x"]);
  });
});

describe("topN", () => {
  const m = new Map([["b", 2], ["a", 2], ["c", 5], ["d", 1]]);
  test("sorted by count desc then word asc", () => {
    expect(topN(m, 4)).toEqual([["c", 5], ["a", 2], ["b", 2], ["d", 1]]);
  });
  test("truncates to n", () => {
    expect(topN(m, 2)).toEqual([["c", 5], ["a", 2]]);
  });
  test("fewer entries than n returns all", () => {
    expect(topN(m, 99)).toHaveLength(4);
  });
  test("n <= 0 gives empty", () => {
    expect(topN(m, 0)).toEqual([]);
    expect(topN(m, -2)).toEqual([]);
  });
  test("tie-break uses code-point order", () => {
    const t = new Map([["é", 1], ["z", 1], ["a", 1], ["B", 1]]);
    expect(topN(t, 4).map((e) => e[0])).toEqual(["B", "a", "z", "é"]);
  });
  test("does not modify input", () => {
    const before = [...m.entries()];
    topN(m, 2);
    expect([...m.entries()]).toEqual(before);
  });
});

describe("cli", () => {
  test("prints word count lines, default top 10", () => {
    const letters = "abcdefghijkl".split("");
    const r = cli(letters.map((l, i) => `${l}${l} `.repeat(12 - i)).join(""));
    expect(r.code).toBe(0);
    expect(r.out.split("\n").filter(Boolean)).toHaveLength(10);
  });
  test("--top N and ordering", () => {
    const r = cli("the cat the dog the cat", "--top", "2");
    expect(r.code).toBe(0);
    expect(r.out).toBe("the 3\ncat 2\n");
  });
  test("--top=N form", () => {
    expect(cli("a a b", "--top=1").out).toBe("a 2\n");
  });
  test("empty input prints nothing, exit 0", () => {
    const r = cli("");
    expect(r.code).toBe(0);
    expect(r.out).toBe("");
  });
  test.each([["0"], ["-3"], ["abc"], ["2.5"]])("invalid N %s exits 2 with usage on stderr", (n) => {
    const r = cli("a b", "--top", n);
    expect(r.code).toBe(2);
    expect(r.out).toBe("");
    expect(r.err.startsWith("usage:")).toBe(true);
  });
  test("missing value and unknown argument exit 2", () => {
    expect(cli("a", "--top").code).toBe(2);
    expect(cli("a", "--bogus").code).toBe(2);
  });
});
