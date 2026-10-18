export function esc(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
}

const HEADING = /^(#{1,6}) +([^\n]+)$/;
const HR = /^(?:-{3,}|\*{3,}|_{3,})$/;
const UL = /^[-*+] +([^\n]*)$/;
const OL = /^[0-9]+\. +([^\n]*)$/;
const CODE = /`([^`]+)`/g;
const IMG = /!\[([^\]]*)\]\(([^)\s]+)\)/g;
const LINK = /\[([^\]]+)\]\(([^)\s]+)\)/g;
const PH_BASE = 0xf0000;
const PH_RE = /[\u{F0000}-\u{FFFFF}]/gu;

function emphasis(t: string): string {
  t = t.replace(/\*\*\*(?!\s)([^\n]+?)(?<!\s)\*\*\*/g, "<strong><em>$1</em></strong>");
  t = t.replace(/\*\*(?!\s)([^\n]+?)(?<!\s)\*\*/g, "<strong>$1</strong>");
  t = t.replace(
    /(?<![A-Za-z0-9])__(?!\s)([^\n]+?)(?<!\s)__(?![A-Za-z0-9])/g,
    "<strong>$1</strong>",
  );
  t = t.replace(/\*(?!\s)([^\n]+?)(?<!\s)\*/g, "<em>$1</em>");
  t = t.replace(/(?<![A-Za-z0-9])_(?!\s)([^\n]+?)(?<!\s)_(?![A-Za-z0-9])/g, "<em>$1</em>");
  return t;
}

function inline(text: string): string {
  const store: string[] = [];
  const ph = (html: string): string => {
    store.push(html);
    return String.fromCodePoint(PH_BASE + store.length - 1);
  };
  text = text.replace(CODE, (_m, c: string) => ph("<code>" + esc(c) + "</code>"));
  text = esc(text);
  text = text.replace(IMG, (_m, alt: string, url: string) => ph(`<img src="${url}" alt="${alt}">`));
  text = text.replace(LINK, (_m, t: string, url: string) =>
    ph(`<a href="${url}">${emphasis(t)}</a>`),
  );
  text = emphasis(text);
  for (;;) {
    const next = text.replace(PH_RE, (m) => store[m.codePointAt(0)! - PH_BASE] ?? m);
    if (next === text) break;
    text = next;
  }
  return text;
}

function startsBlock(line: string): boolean {
  return (
    line.startsWith("```") ||
    HEADING.test(line) ||
    HR.test(line) ||
    line.startsWith(">") ||
    UL.test(line) ||
    OL.test(line)
  );
}

export function render(md: string): string {
  md = md.replaceAll("\r\n", "\n");
  const raw = md.split("\n");
  const blocks: string[] = [];
  let i = 0;
  const n = raw.length;
  while (i < n) {
    const line = raw[i].trimEnd();
    if (line === "") {
      i++;
      continue;
    }
    if (line.startsWith("```")) {
      const info = line.slice(3).trim();
      const lang = info ? info.split(/\s+/)[0] : "";
      i++;
      const code: string[] = [];
      while (i < n && raw[i].trimEnd() !== "```") {
        code.push(raw[i]);
        i++;
      }
      if (i < n) i++;
      const body = esc(code.join("\n"));
      blocks.push(
        lang
          ? `<pre><code class="language-${esc(lang)}">${body}</code></pre>`
          : `<pre><code>${body}</code></pre>`,
      );
      continue;
    }
    const m = HEADING.exec(line);
    if (m) {
      const lvl = m[1].length;
      blocks.push(`<h${lvl}>${inline(m[2])}</h${lvl}>`);
      i++;
      continue;
    }
    if (HR.test(line)) {
      blocks.push("<hr>");
      i++;
      continue;
    }
    if (line.startsWith(">")) {
      const inner: string[] = [];
      while (i < n && raw[i].trimEnd().startsWith(">")) {
        let l = raw[i].trimEnd().slice(1);
        if (l.startsWith(" ")) l = l.slice(1);
        inner.push(l);
        i++;
      }
      const html = render(inner.join("\n"));
      blocks.push(html === "" ? "<blockquote></blockquote>" : `<blockquote>\n${html}\n</blockquote>`);
      continue;
    }
    const isUl = UL.test(line);
    if (isUl || OL.test(line)) {
      const rx = isUl ? UL : OL;
      const tag = isUl ? "ul" : "ol";
      const items: string[] = [];
      while (i < n) {
        const mm = rx.exec(raw[i].trimEnd());
        if (!mm) break;
        items.push(`<li>${inline(mm[1])}</li>`);
        i++;
      }
      blocks.push(`<${tag}>\n` + items.join("\n") + `\n</${tag}>`);
      continue;
    }
    const para = [line.trim()];
    i++;
    while (i < n) {
      const l = raw[i].trimEnd();
      if (l === "" || startsBlock(l)) break;
      para.push(l.trim());
      i++;
    }
    blocks.push("<p>" + inline(para.join("\n")) + "</p>");
  }
  return blocks.join("\n");
}
