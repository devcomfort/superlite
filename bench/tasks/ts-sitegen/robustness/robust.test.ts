import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { parse } from "../src/frontmatter.js";
import { render } from "../src/markdown.js";
import { slugify } from "../src/slug.js";
import { tokenize } from "../src/search.js";
import { build } from "../src/site.js";
import { makeTempDir, readText, siteFactory, writeFiles } from "./helpers.js";

describe("robustness", () => {
  test("5 MB markdown document renders in under 20 s", () => {
    const para = "Some *emphasis* and **strong** text with a [link](http://x.com/a_b) and `code <span>` here, snake_case_word.\n";
    const parts: string[] = [];
    let size = 0;
    while (size < 5 * 1024 * 1024) {
      parts.push(para.repeat(4));
      parts.push("\n");
      size += para.length * 4 + 1;
    }
    const md = parts.join("");
    const t0 = Date.now();
    const html = render(md);
    const dt = Date.now() - t0;
    expect(dt).toBeLessThan(20_000);
    expect(html.startsWith("<p>Some <em>emphasis</em> and <strong>strong</strong>")).toBe(true);
    expect(html.endsWith("</p>")).toBe(true);
  }, 60_000);

  test("build of 1500 posts under 60 s with correct counts", () => {
    const files: Record<string, string> = {};
    const N = 1500;
    for (let i = 0; i < N; i++) {
      const n = String(i).padStart(4, "0");
      const day = String((i % 28) + 1).padStart(2, "0");
      files[`content/p${n}.md`] =
        `---\ntitle: Post ${i}\ndate: 2023-05-${day}\ntags: [t${i % 10}, common]\n---\nBody of *post* ${i} with [a link](/posts/x/).\n`;
    }
    files["content/draft.md"] = "---\ntitle: D\ndraft: true\n---\nx";
    const { src, out } = siteFactory({ ...files, "content/a.md": null, "content/b.md": null, "content/d.md": null });
    const t0 = Date.now();
    const report = build(src, out);
    const dt = Date.now() - t0;
    expect(dt).toBeLessThan(60_000);
    expect(report.posts).toBe(N);
    expect(report.drafts).toBe(1);
    expect(report.tagPages).toBe(11);
    expect(report.staticFiles).toBe(1);
    expect(report.outputFiles.length).toBe(N + 11 + 1 + 2 + 1);
    const sorted = [...report.outputFiles].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    expect(report.outputFiles).toEqual(sorted);
    expect(fs.existsSync(path.join(out, "posts", "post-1499", "index.html"))).toBe(true);
    JSON.parse(readText(out, "search.json"));
  }, 120_000);

  test("unicode end to end", () => {
    const title = "Café 日本語 😀 naïve";
    const body = "Ünïcödé *émphasis* 日本語のテキスト 😀 and `código`\n\n- 項目 one\n- ítem two\n";
    const text = `---\ntitle: ${title}\ndate: 2024-03-03\ntags: [Ünï, 日本]\nsummary: "résumé 😀"\n---\n${body}`;

    const fm = parse(text);
    expect(fm.meta.title).toBe(title);
    expect(fm.meta.summary).toBe("résumé 😀");
    expect(fm.meta.tags).toEqual(["Ünï", "日本"]);
    expect(fm.body).toBe(body);

    const html = render(fm.body);
    expect(html).toContain("<em>émphasis</em>");
    expect(html).toContain("日本語のテキスト 😀");
    expect(html).toContain("<code>código</code>");
    expect(html).toContain("<li>項目 one</li>");

    expect(slugify(title)).toBe("cafe-naive");
    expect(slugify("日本語 😀")).toBe("");
    expect(tokenize("Café 日本語 😀 naïve x1")).toEqual(["caf", "na", "ve", "x1"]);

    const { src, out } = siteFactory({
      "content/a.md": text,
      "content/b.md": null,
      "content/d.md": null,
      "templates/post.html": "<h1>{{ post.title }}</h1>{{ post.content|safe }}|{{ post.summary }}",
    });
    const report = build(src, out);
    expect(report.posts).toBe(1);
    const page = readText(out, "posts/cafe-naive/index.html");
    expect(page).toContain("<h1>Café 日本語 😀 naïve</h1>");
    expect(page).toContain("résumé 😀");
    const idx = JSON.parse(readText(out, "search.json"));
    expect(idx.docs["cafe-naive"].title).toBe(title);
    expect(Object.keys(idx.terms)).toContain("caf");
    expect(readText(out, "feed.xml")).toContain("<title>Café 日本語 😀 naïve</title>");
    // tag slugs of non-ASCII tags: "Ünï" -> "uni", "日本" -> none
    expect(report.tagPages).toBe(1);
    void makeTempDir;
    void writeFiles;
  });
});
