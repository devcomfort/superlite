import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { BuildError } from "../src/errors.js";
import { build as b } from "../src/site.js";
import { type Overrides, readText as read, siteFactory } from "./helpers.js";

const EXPECTED_FILES = [
  "css/s.css",
  "feed.xml",
  "index.html",
  "posts/hello-world-2/index.html",
  "posts/hello-world/index.html",
  "search.json",
  "tags/python/index.html",
  "tags/web-dev/index.html",
];

function build(overrides: Overrides = {}) {
  const { src, out } = siteFactory(overrides);
  return { report: b(src, out), src, out };
}

/** Compact JSON text with all object keys sorted by code point (no integer-like keys used here). */
function sortedJson(v: unknown): string {
  const norm = (x: any): any => {
    if (Array.isArray(x)) return x.map(norm);
    if (x && typeof x === "object") {
      const o: Record<string, any> = {};
      for (const k of Object.keys(x).sort()) o[k] = norm(x[k]);
      return o;
    }
    return x;
  };
  return JSON.stringify(norm(v));
}

describe("site", () => {
  test("report for spec example", () => {
    const { report } = build();
    expect(report.posts).toBe(2);
    expect(report.drafts).toBe(1);
    expect(report.tagPages).toBe(2);
    expect(report.staticFiles).toBe(1);
    expect(report.outputFiles).toEqual(EXPECTED_FILES);
  });

  test("post page is template output exactly", () => {
    const { out } = build();
    expect(read(out, "posts/hello-world-2/index.html")).toBe("<h1>Hello World</h1>\n<p>Hi <em>you</em></p>");
  });

  test("index lists posts by date desc and tags by slug", () => {
    const { out } = build();
    expect(read(out, "index.html")).toBe("hello-world,hello-world-2,|python=1 web-dev=1 ");
  });

  test("tag page context", () => {
    const { out } = build();
    expect(read(out, "tags/python/index.html")).toBe("Python:1:hello-world-2;");
    expect(read(out, "tags/web-dev/index.html")).toBe("web dev:1:hello-world-2;");
  });

  test("post tag_links shape", () => {
    const tpl = "{% for l in post.tag_links %}{{ l.name }}|{{ l.slug }}|{{ l.url }};{% endfor %}[{{ post.url }}]";
    const { out } = build({ "templates/post.html": tpl });
    expect(read(out, "posts/hello-world-2/index.html")).toBe(
      "Python|python|/tags/python/;web dev|web-dev|/tags/web-dev/;[/posts/hello-world-2/]",
    );
    expect(read(out, "posts/hello-world/index.html")).toBe("[/posts/hello-world/]");
  });

  test("feed is valid rss with posts newest first", () => {
    const { out } = build();
    const xml = read(out, "feed.xml");
    expect(
      xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n<channel>\n<title>My Blog</title>'),
    ).toBe(true);
    const links = [...xml.matchAll(/<item>\n<title>[^\n]*<\/title>\n<link>([^<]*)<\/link>/g)].map((m) => m[1]);
    expect(links).toEqual(["https://example.com/posts/hello-world/", "https://example.com/posts/hello-world-2/"]);
    expect(xml).toContain("<pubDate>Fri, 05 Jan 2024 00:00:00 +0000</pubDate>");
    expect(xml.endsWith("</channel>\n</rss>")).toBe(true);
  });

  test("search.json exact", () => {
    const { out } = build();
    const expected = {
      docs: {
        "hello-world": { title: "Hello World", length: 3 },
        "hello-world-2": { title: "Hello World", length: 4 },
      },
      terms: {
        hello: { "hello-world": 1, "hello-world-2": 1 },
        hi: { "hello-world-2": 1 },
        world: { "hello-world": 1, "hello-world-2": 1 },
        x: { "hello-world": 1 },
        you: { "hello-world-2": 1 },
      },
    };
    const text = read(out, "search.json");
    expect(JSON.parse(text)).toEqual(expected);
    expect(text).toBe(sortedJson(expected));
  });

  test("static files copied byte for byte", () => {
    const { out } = build();
    const got = fs.readFileSync(path.join(out, "css", "s.css"));
    expect([...got]).toEqual([...Buffer.from("body{color:red}\r\n", "utf8"), 0x00, 0xff]);
  });

  test("existing output contents not removed", () => {
    const { src, out } = siteFactory();
    fs.mkdirSync(out);
    fs.writeFileSync(path.join(out, "old.txt"), "keep");
    fs.writeFileSync(path.join(out, "index.html"), "stale");
    const report = b(src, out);
    expect(fs.readFileSync(path.join(out, "old.txt"), "utf8")).toBe("keep");
    expect(report.outputFiles).not.toContain("old.txt");
    expect(read(out, "index.html")).not.toBe("stale");
  });

  test("empty tag slug and duplicate tags in post", () => {
    const post = "---\ntitle: T\ndate: 2024-02-02\ntags: [Py, py, '!!!', Zed]\n---\nbody";
    const tpl = "{% for l in post.tag_links %}{{ l.name }},{% endfor %}|{{ post.tags|length }}";
    const { report, out } = build({
      "content/a.md": post,
      "content/b.md": null,
      "content/d.md": null,
      "templates/post.html": tpl,
      "templates/index.html": "{% for t in tags %}{{ t.name }}:{{ t.count }};{% endfor %}",
    });
    expect(report.tagPages).toBe(2);
    expect(read(out, "posts/t/index.html")).toBe("Py,Zed,|4");
    expect(read(out, "index.html")).toBe("Py:1;Zed:1;");
  });

  test.each(["site.json", "templates/post.html", "templates/index.html", "templates/tag.html"])(
    "build error for missing input %s",
    (rel) => {
      const { src, out } = siteFactory({ [rel]: null });
      expect(() => b(src, out)).toThrow(BuildError);
    },
  );

  test("build error for missing src dir", () => {
    const { out } = siteFactory();
    expect(() => b(path.join(path.dirname(out), "does-not-exist"), out)).toThrow(BuildError);
  });

  test.each([
    "---\ntitle: T\ndate: 2024-13-01\n---\n",
    "---\ntitle: T\n---\n",
    "---\ndate: 2024-01-01\n---\n",
    "---\ntitle: T\ndate: 2024-01-01\ndraft: yes\n---\n",
    "---\ntitle: T\ndate: 2024-01-01\ntags: x\n---\n",
    "---\ntitle: T\ndate: 2024-01-01\n",
  ])("build error for invalid content %#", (text) => {
    const { src, out } = siteFactory({ "content/z.md": text });
    expect(() => b(src, out)).toThrow(BuildError);
  });

  test("static file colliding with generated file is BuildError", () => {
    const { src, out } = siteFactory({ "static/feed.xml": "x" });
    expect(() => b(src, out)).toThrow(BuildError);
  });

  test("content filtering ignores hidden, non-md and subdirs", () => {
    const good = "---\ntitle: Only\ndate: 2024-01-01\n---\n";
    const { report, out } = build({
      "content/a.md": good,
      "content/b.md": null,
      "content/d.md": null,
      "content/.hidden.md": "garbage",
      "content/notes.txt": "garbage",
      "content/sub/x.md": "garbage",
    });
    expect(report.posts).toBe(1);
    expect(read(out, "index.html")).toBe("only,|");
  });
});
