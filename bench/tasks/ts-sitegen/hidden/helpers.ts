import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll } from "vitest";

export type Overrides = Record<string, string | Buffer | null>;

export const BASE_FILES: Record<string, string | Buffer> = {
  "site.json": '{"title": "My Blog", "url": "https://example.com/", "author": "A"}\n',
  "templates/post.html": "<h1>{{ post.title }}</h1>\n{{ post.content|safe }}",
  "templates/index.html":
    "{% for p in posts %}{{ p.slug }},{% endfor %}|" +
    "{% for t in tags %}{{ t.slug }}={{ t.count }} {% endfor %}",
  "templates/tag.html":
    "{{ tag.name }}:{{ tag.count }}:{% for p in posts %}{{ p.slug }};{% endfor %}",
  "content/b.md":
    "---\ntitle: Hello World\ndate: 2024-01-02\ntags: [Python, web dev]\n---\nHi *you*",
  "content/a.md": "---\ntitle: Hello World\ndate: 2024-01-05\ndraft: false\n---\nx",
  "content/d.md": "---\ndraft: true\n---\nsecret",
  "static/css/s.css": Buffer.concat([
    Buffer.from("body{color:red}\r\n", "utf8"),
    Buffer.from([0x00, 0xff]),
  ]),
};

const tempDirs: string[] = [];

export function makeTempDir(prefix = "sitegen-"): string {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}

afterAll(() => {
  for (const d of tempDirs.splice(0)) {
    try {
      fs.rmSync(d, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  }
});

/** Write `files` (null = skip) below `root`. */
export function writeFiles(root: string, files: Record<string, string | Buffer | null>): void {
  fs.mkdirSync(root, { recursive: true });
  for (const [rel, data] of Object.entries(files)) {
    if (data === null) continue;
    const p = path.join(root, ...rel.split("/"));
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, typeof data === "string" ? Buffer.from(data, "utf8") : data);
  }
}

/** site_factory equivalent: fresh temp dir; returns { src, out } (out not created). */
export function siteFactory(overrides: Overrides = {}): { src: string; out: string } {
  const root = makeTempDir();
  const files: Record<string, string | Buffer | null> = { ...BASE_FILES, ...overrides };
  const src = path.join(root, "src");
  const out = path.join(root, "out");
  writeFiles(src, files);
  return { src, out };
}

export function readText(out: string, rel: string): string {
  return fs.readFileSync(path.join(out, ...rel.split("/"))).toString("utf8");
}

export interface Captured {
  io: { out(text: string): void; err(text: string): void };
  stdout: () => string;
  stderr: () => string;
}

/** Capture helper for main(argv, io). */
export function capture(): Captured {
  let o = "";
  let e = "";
  return {
    io: {
      out(t: string) {
        o += t;
      },
      err(t: string) {
        e += t;
      },
    },
    stdout: () => o,
    stderr: () => e,
  };
}
