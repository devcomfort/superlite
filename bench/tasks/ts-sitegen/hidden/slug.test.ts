import { describe, expect, test } from "vitest";
import { slugify, uniqueSlug } from "../src/slug.js";

describe("slug", () => {
  test("slugify examples", () => {
    expect(slugify("Hello, World!")).toBe("hello-world");
    expect(slugify("  Multiple   Spaces  ")).toBe("multiple-spaces");
    expect(slugify("C++ & Rust")).toBe("c-rust");
    expect(slugify("Don't Stop")).toBe("don-t-stop");
    expect(slugify("snake_case v1.2.3")).toBe("snake-case-v1-2-3");
  });
  test("accents dropped", () => {
    expect(slugify("Café Münster")).toBe("cafe-munster");
  });
  test("can return empty", () => {
    expect(slugify("---")).toBe("");
    expect(slugify("")).toBe("");
    expect(slugify("日本語")).toBe("");
  });
  test("unique slug collisions", () => {
    expect(uniqueSlug("Hello", new Set())).toBe("hello");
    expect(uniqueSlug("Hello", new Set(["hello"]))).toBe("hello-2");
    expect(uniqueSlug("Hello", new Set(["hello", "hello-2"]))).toBe("hello-3");
    expect(uniqueSlug("Hello 2", new Set(["hello-2"]))).toBe("hello-2-2");
  });
  test("untitled and no mutation", () => {
    expect(uniqueSlug("!!!", new Set())).toBe("untitled");
    expect(uniqueSlug("!!!", new Set(["untitled"]))).toBe("untitled-2");
    const taken = new Set(["hello"]);
    uniqueSlug("Hello", taken);
    expect([...taken]).toEqual(["hello"]);
  });
});
