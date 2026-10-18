import { describe, expect, test } from "vitest";
import { ValueError } from "../src/errors.js";
import { buildIndex, search, tokenize } from "../src/search.js";

const DOCS = [
  { slug: "b", title: "Beta", text: "the beta and alpha" },
  { slug: "a", title: "Alpha", text: "alpha alpha" },
];

const idx = (docs = DOCS) => buildIndex(docs);

describe("search", () => {
  test("tokenize examples", () => {
    expect(tokenize("The Cat & the HAT, x2!")).toEqual(["cat", "hat", "x2"]);
    expect(tokenize("café")).toEqual(["caf"]);
    expect(tokenize("go go x")).toEqual(["go", "go", "x"]);
  });

  test("build index example", () => {
    expect(idx()).toEqual({
      docs: { a: { title: "Alpha", length: 3 }, b: { title: "Beta", length: 3 } },
      terms: { alpha: { a: 3, b: 1 }, beta: { b: 2 } },
    });
  });

  test("build index empty", () => {
    expect(idx([])).toEqual({ docs: {}, terms: {} });
  });

  test("build index invalid docs raise ValueError", () => {
    expect(() =>
      buildIndex([
        { slug: "a", title: "t", text: "x" },
        { slug: "a", title: "u", text: "y" },
      ]),
    ).toThrow(ValueError);
    expect(() => buildIndex([{ slug: "a", title: "t" } as any])).toThrow(ValueError);
  });

  test("search basic and case-insensitive with limit", () => {
    const index = idx();
    expect(search(index, "alpha")).toEqual(["a", "b"]);
    expect(search(index, "ALPHA", 1)).toEqual(["a"]);
  });

  test("search requires all terms", () => {
    expect(search(idx(), "alpha beta")).toEqual(["b"]);
  });

  test("duplicate query terms count once", () => {
    expect(search(idx(), "alpha alpha")).toEqual(["a", "b"]);
  });

  test("no results cases", () => {
    const index = idx();
    expect(search(index, "the of")).toEqual([]);
    expect(search(index, "zzz")).toEqual([]);
    expect(search(index, "")).toEqual([]);
    expect(search(index, "alpha zzz")).toEqual([]);
  });

  test("ties sorted by slug", () => {
    const index = idx([
      { slug: "z", title: "foo", text: "" },
      { slug: "m", title: "foo", text: "" },
    ]);
    expect(search(index, "foo")).toEqual(["m", "z"]);
  });
});
