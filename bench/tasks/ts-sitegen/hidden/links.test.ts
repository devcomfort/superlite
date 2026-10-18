import { describe, expect, test } from "vitest";
import { ValueError } from "../src/errors.js";
import { findBrokenLinks as F } from "../src/links.js";

describe("links", () => {
  test("missing target is reported", () => {
    const pages = {
      "/index.html": '<a href="/about.html">A</a> <a href="/missing.html">M</a>',
      "/about.html": "",
    };
    expect(F(pages)).toEqual([["/index.html", "/missing.html"]]);
  });

  test("relative directory links resolve to index", () => {
    const pages = {
      "/posts/a/index.html": '<a href="../b/">x</a><a href="../c/">y</a>',
      "/posts/b/index.html": "",
    };
    expect(F(pages)).toEqual([["/posts/a/index.html", "../c/"]]);
  });

  test("fragments check ids in target page", () => {
    const pages = {
      "/index.html":
        '<h2 id="s1">h</h2><a href="#s1">1</a><a href="#s2">2</a>' +
        '<a href="/other.html#z">3</a><a href="/other.html#y">4</a>',
      "/other.html": "<p id='y'></p>",
    };
    expect(F(pages)).toEqual([
      ["/index.html", "#s2"],
      ["/index.html", "/other.html#z"],
    ]);
  });

  test("skipped hrefs and case-insensitive attribute", () => {
    const pages = {
      "/index.html":
        '<a href="https://x.com/a">e</a><a href="mailto:a@b.c">m</a>' +
        '<a href="//cdn.x/y">c</a><a href="">e</a><a HREF="/nope">n</a>',
    };
    expect(F(pages)).toEqual([["/index.html", "/nope"]]);
  });

  test("path resolution rules", () => {
    const pages = {
      "/index.html":
        '<a href="posts/p">1</a><a href="./posts/p/">2</a>' +
        '<a href="/style.css">3</a><a href="/style.css#x">4</a>' +
        '<a href="?q=1">5</a><a href=\'/../index.html\'>6</a>',
      "/posts/p/index.html": "",
      "/style.css": "",
    };
    expect(F(pages)).toEqual([["/index.html", "/style.css#x"]]);
  });

  test("output sorted by page and duplicates kept", () => {
    const pages = {
      "/b.html": '<a href="/z">1</a>',
      "/a.html": '<a href="/y">2</a><a href="/y">3</a>',
    };
    expect(F(pages)).toEqual([
      ["/a.html", "/y"],
      ["/a.html", "/y"],
      ["/b.html", "/z"],
    ]);
  });

  test("non-absolute page path raises ValueError", () => {
    expect(() => F({ "index.html": "" })).toThrow(ValueError);
  });
});
