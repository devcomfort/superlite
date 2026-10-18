import { describe, expect, test } from "vitest";
import { render as R } from "../src/markdown.js";

describe("markdown", () => {
  test("heading", () => {
    expect(R("# Hello")).toBe("<h1>Hello</h1>");
  });
  test("emphasis and strong", () => {
    expect(R("Hello *world* and **bold**")).toBe("<p>Hello <em>world</em> and <strong>bold</strong></p>");
  });
  test("html escaping of quotes and symbols", () => {
    expect(R("a < b & \"c\" 'd'")).toBe("<p>a &lt; b &amp; &quot;c&quot; &#x27;d&#x27;</p>");
  });
  test("raw html is escaped", () => {
    expect(R("<script>alert(1)</script>")).toBe("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>");
  });
  test("paragraphs, soft breaks and no trailing newline", () => {
    expect(R("para one\nstill one\n\n\npara two\n")).toBe("<p>para one\nstill one</p>\n<p>para two</p>");
  });
  test("unordered and ordered lists", () => {
    expect(R("- a\n- b\n\n1. x\n2. y")).toBe(
      "<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n<ol>\n<li>x</li>\n<li>y</li>\n</ol>",
    );
  });
  test("fenced code with language", () => {
    const md = "```python\nprint('<hi>')\n```";
    expect(R(md)).toBe('<pre><code class="language-python">print(&#x27;&lt;hi&gt;&#x27;)</code></pre>');
  });
  test("blockquote renders recursively", () => {
    expect(R("> quote *x*\n> more")).toBe("<blockquote>\n<p>quote <em>x</em>\nmore</p>\n</blockquote>");
  });
  test("link url is not emphasis processed and is escaped", () => {
    expect(R("[a](http://x.com/a_b_c?q=1&r=2)")).toBe('<p><a href="http://x.com/a_b_c?q=1&amp;r=2">a</a></p>');
  });
  test("image", () => {
    expect(R("![alt](/i.png)")).toBe('<p><img src="/i.png" alt="alt"></p>');
  });
  test("strong emphasis triple star", () => {
    expect(R("***bold italic***")).toBe("<p><strong><em>bold italic</em></strong></p>");
  });
  test("nested emphasis", () => {
    expect(R("**bold with *nested em* inside** and *em with **strong** inside*")).toBe(
      "<p><strong>bold with <em>nested em</em> inside</strong> and " +
        "<em>em with <strong>strong</strong> inside</em></p>",
    );
  });
  test("code span and non-emphasis stars and underscores", () => {
    expect(R("use `a<b` and snake_case_name, 2 * 3 * 4")).toBe(
      "<p>use <code>a&lt;b</code> and snake_case_name, 2 * 3 * 4</p>",
    );
  });
  test("empty and whitespace-only input", () => {
    expect(R("")).toBe("");
    expect(R("\n\n  \n")).toBe("");
  });
  test("blank line starts new list", () => {
    expect(R("- a\n\n- b")).toBe("<ul>\n<li>a</li>\n</ul>\n<ul>\n<li>b</li>\n</ul>");
  });
  test("hr after text ends paragraph, no setext", () => {
    expect(R("## Title\ntext\n---\nmore")).toBe("<h2>Title</h2>\n<p>text</p>\n<hr>\n<p>more</p>");
  });
});
