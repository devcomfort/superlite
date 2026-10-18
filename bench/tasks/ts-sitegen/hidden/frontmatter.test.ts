import { describe, expect, test } from "vitest";
import { FrontmatterError } from "../src/errors.js";
import { parse } from "../src/frontmatter.js";

describe("frontmatter", () => {
  test("no frontmatter returns empty meta and text", () => {
    expect(parse("hello")).toEqual({ meta: {}, body: "hello" });
  });

  test("basic title and body", () => {
    expect(parse("---\ntitle: Hi\n---\nBody\n")).toEqual({ meta: { title: "Hi" }, body: "Body\n" });
  });

  test("crlf is normalized", () => {
    expect(parse("---\r\ntitle: Hi\r\n---\r\nB")).toEqual({ meta: { title: "Hi" }, body: "B" });
  });

  test("scalar types and quotes", () => {
    const text = "---\nn: 42\nok: true\nno: false\ns: \"a: b\"\nt: 'it''s'\n---\n";
    expect(parse(text)).toEqual({
      meta: { n: 42, ok: true, no: false, s: "a: b", t: "it's" },
      body: "",
    });
  });

  test("inline lists and empty value", () => {
    const text = '---\ntags: [a, "b, c", 3, true]\nempty: []\ne:\n---\nx';
    expect(parse(text)).toEqual({
      meta: { tags: ["a", "b, c", 3, true], empty: [], e: "" },
      body: "x",
    });
  });

  test("comments, blank lines, dates and verbatim body", () => {
    const text = "---\n# note\n\ndate: 2024-01-15\nslug: -x\n---\n\n\nbody";
    expect(parse(text)).toEqual({ meta: { date: "2024-01-15", slug: "-x" }, body: "\n\nbody" });
  });

  test("empty block", () => {
    expect(parse("---\n---\nbody")).toEqual({ meta: {}, body: "body" });
  });

  test("plain string edge cases and ints", () => {
    const { meta } = parse("---\na: True\nb: yes\nc: 007\nd: -5\ne: b: c\nf: null\ng: x # y\nh: 1.5\n---\n");
    expect(meta).toEqual({ a: "True", b: "yes", c: 7, d: -5, e: "b: c", f: "null", g: "x # y", h: "1.5" });
    expect(Object.keys(meta)).toEqual("abcdefgh".split(""));
  });

  test.each([
    ["no closing line", "---\ntitle: x\n"],
    ["missing colon", "---\ntitle x\n---\n"],
    ["duplicate key", "---\na: 1\na: 2\n---\n"],
    ["unterminated list", "---\na: [1,\n---\n"],
    ["unterminated dquote", '---\na: "unterminated\n---\n'],
    ["bad escape", '---\na: "x\\q"\n---\n'],
    ["trailing after squote", "---\na: 'x' y\n---\n"],
    ["empty list item", "---\na: [a,,b]\n---\n"],
    ["trailing comma", "---\na: [a,]\n---\n"],
    ["nested list", "---\na: [[x]]\n---\n"],
    ["indented key", "---\n  a: 1\n---\n"],
  ])("invalid frontmatter raises FrontmatterError: %s", (_n, text) => {
    expect(() => parse(text)).toThrow(FrontmatterError);
  });
});
