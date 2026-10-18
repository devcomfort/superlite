import { describe, expect, test } from "vitest";
import { ValueError } from "../src/errors.js";
import { buildRss } from "../src/feed.js";

const SITE = { title: "My Blog", url: "https://example.com/", author: "A" };

function post(over: Record<string, string> = {}): any {
  return { title: "T", url: "/p/", date: "2024-01-15", ...over };
}

describe("feed", () => {
  test("rss exact example", () => {
    const posts = [
      { title: "First & Best", url: "/posts/first/", date: "2024-01-15", summary: "Hi <you>" },
    ];
    const expected = [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<rss version="2.0">',
      "<channel>",
      "<title>My Blog</title>",
      "<link>https://example.com/</link>",
      "<description>My Blog</description>",
      "<item>",
      "<title>First &amp; Best</title>",
      "<link>https://example.com/posts/first/</link>",
      "<guid>https://example.com/posts/first/</guid>",
      "<pubDate>Mon, 15 Jan 2024 00:00:00 +0000</pubDate>",
      "<description>Hi &lt;you&gt;</description>",
      "</item>",
      "</channel>",
      "</rss>",
    ].join("\n");
    expect(buildRss(SITE, posts)).toBe(expected);
  });

  test("rss no posts", () => {
    const expected = [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<rss version="2.0">',
      "<channel>",
      "<title>My Blog</title>",
      "<link>https://example.com/</link>",
      "<description>My Blog</description>",
      "</channel>",
      "</rss>",
    ].join("\n");
    expect(buildRss(SITE, [])).toBe(expected);
  });

  test("rss pubDate formats", () => {
    const out = buildRss(SITE, [post({ date: "2024-03-01" }), post({ url: "/q/", date: "2023-12-25" })]);
    expect(out).toContain("<pubDate>Fri, 01 Mar 2024 00:00:00 +0000</pubDate>");
    expect(out).toContain("<pubDate>Mon, 25 Dec 2023 00:00:00 +0000</pubDate>");
  });

  test("rss limits to 20 newest items", () => {
    const pad = (n: number) => String(n).padStart(2, "0");
    const posts = Array.from({ length: 21 }, (_, i) =>
      post({ title: `P${pad(i)}`, url: `/p${pad(i)}/`, date: `2024-01-${pad(i + 1)}` }),
    );
    const out = buildRss(SITE, posts);
    expect(out.split("<item>").length - 1).toBe(20);
    expect(out).not.toContain("<title>P00</title>");
    expect(out).toContain("<title>P20</title>");
  });

  test("sorted by date desc then url asc and input not mutated", () => {
    const posts = [
      post({ title: "old", url: "/o/", date: "2020-01-01" }),
      post({ title: "b", url: "/b/", date: "2024-05-05" }),
      post({ title: "a", url: "/a/", date: "2024-05-05" }),
      post({ title: "new", url: "/n/", date: "2025-01-01" }),
    ];
    const snapshot = structuredClone(posts);
    const out = buildRss(SITE, posts);
    const titles = out.split("\n").filter((l) => l.startsWith("<title>")).slice(1);
    expect(titles).toEqual(["<title>new</title>", "<title>a</title>", "<title>b</title>", "<title>old</title>"]);
    expect(posts).toEqual(snapshot);
  });

  test("links use stripped base and missing summary gives empty description", () => {
    const out = buildRss({ title: "S", url: "https://x.org//" }, [post({ url: "posts/z/" })]);
    const lines = out.split("\n");
    expect(lines).toContain("<link>https://x.org/</link>");
    expect(lines).toContain("<link>https://x.org/posts/z/</link>");
    expect(lines).toContain("<guid>https://x.org/posts/z/</guid>");
    expect(lines[lines.length - 4]).toBe("<description></description>");
  });

  test.each([
    [{ title: "x" }, []],
    [{ url: "x" }, []],
    [SITE, [{ title: "t", url: "/u/" }]],
    [SITE, [{ title: "t", date: "2024-01-01" }]],
    [SITE, [post({ date: "2024-02-30" })]],
    [SITE, [post({ date: "2024-1-5" })]],
  ])("invalid input raises ValueError (%#)", (site, posts) => {
    expect(() => buildRss(site as any, posts as any)).toThrow(ValueError);
  });
});
