import fs from "node:fs";
import path from "node:path";
import * as frontmatter from "./frontmatter.js";
import type { Value } from "./frontmatter.js";
import * as markdown from "./markdown.js";
import * as templates from "./templates.js";
import { BuildError, FrontmatterError, SitegenError, TemplateError, ValueError } from "./errors.js";
import { buildRss } from "./feed.js";
import { buildIndex } from "./search.js";
import { slugify, uniqueSlug } from "./slug.js";
import { cmp, isValidDate } from "./util.js";

export interface BuildReport {
  posts: number;
  drafts: number;
  tagPages: number;
  staticFiles: number;
  outputFiles: string[];
}

type Obj = { [key: string]: Value };

const DECODER = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

function msg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function readText(p: string): string {
  try {
    return DECODER.decode(fs.readFileSync(p));
  } catch (e) {
    throw new BuildError(`${p}: cannot read: ${msg(e)}`, { cause: e });
  }
}

function isDir(p: string): boolean {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

function isFile(p: string): boolean {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
}

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function renderTpl(p: string, template: string, context: Record<string, Value>): string {
  try {
    return templates.render(template, context);
  } catch (e) {
    if (e instanceof TemplateError) throw new BuildError(`${p}: ${e.message}`, { cause: e });
    throw e;
  }
}

/** JSON text with every object's keys sorted by code point, no whitespace. */
function stableJson(v: unknown): string {
  if (Array.isArray(v)) return "[" + v.map(stableJson).join(",") + "]";
  if (typeof v === "object" && v !== null) {
    const o = v as Record<string, unknown>;
    const keys = Object.keys(o).sort(cmp);
    return "{" + keys.map((k) => JSON.stringify(k) + ":" + stableJson(o[k])).join(",") + "}";
  }
  return JSON.stringify(v);
}

interface Post {
  map: Obj;
  body: string;
  tagSlugs: string[];
}

function walkStatic(dir: string, rel: string, acc: Map<string, string>): void {
  const names = fs.readdirSync(dir).sort(cmp);
  for (const name of names) {
    const full = path.join(dir, name);
    const r = rel === "" ? name : rel + "/" + name;
    if (isDir(full)) walkStatic(full, r, acc);
    else acc.set(r, full);
  }
}

export function build(src: string, out: string): BuildReport {
  if (!isDir(src)) throw new BuildError(`source directory not found: ${src}`);

  const sitePath = path.join(src, "site.json");
  if (!isFile(sitePath)) throw new BuildError(`${sitePath}: not found`);
  const siteText = readText(sitePath);
  let siteRaw: unknown;
  try {
    siteRaw = JSON.parse(siteText);
  } catch (e) {
    throw new BuildError(`${sitePath}: invalid JSON: ${msg(e)}`, { cause: e });
  }
  if (!isObj(siteRaw)) throw new BuildError(`${sitePath}: must be a JSON object`);
  const site = siteRaw;
  for (const key of ["title", "url", "author"]) {
    if (!Object.hasOwn(site, key)) throw new BuildError(`${sitePath}: missing required key '${key}'`);
    if (typeof site[key] !== "string") throw new BuildError(`${sitePath}: key '${key}' must be a string`);
  }

  const tpl: Record<string, { p: string; text: string }> = {};
  for (const name of ["post", "index", "tag"]) {
    const p = path.join(src, "templates", `${name}.html`);
    if (!isFile(p)) throw new BuildError(`${p}: template not found`);
    tpl[name] = { p, text: readText(p) };
  }

  const contentDir = path.join(src, "content");
  let files: string[] = [];
  if (isDir(contentDir)) {
    let entries: string[];
    try {
      entries = fs.readdirSync(contentDir);
    } catch (e) {
      throw new BuildError(`${contentDir}: ${msg(e)}`, { cause: e });
    }
    files = entries
      .filter((n) => n.endsWith(".md") && !n.startsWith(".") && isFile(path.join(contentDir, n)))
      .sort(cmp);
  }

  const taken = new Set<string>();
  const posts: Post[] = [];
  let drafts = 0;
  for (const name of files) {
    const f = path.join(contentDir, name);
    const text = readText(f);
    let meta: Record<string, Value>;
    let body: string;
    try {
      ({ meta, body } = frontmatter.parse(text));
    } catch (e) {
      if (e instanceof FrontmatterError) throw new BuildError(`${f}: ${e.message}`, { cause: e });
      throw e;
    }
    if (Object.hasOwn(meta, "draft")) {
      if (typeof meta.draft !== "boolean") throw new BuildError(`${f}: 'draft' must be a boolean`);
      if (meta.draft) {
        drafts++;
        continue;
      }
    }
    const title = meta.title;
    if (!Object.hasOwn(meta, "title") || typeof title !== "string" || title.trim() === "") {
      throw new BuildError(`${f}: 'title' is required and must be a non-empty string`);
    }
    const date = meta.date;
    if (!Object.hasOwn(meta, "date") || !isValidDate(date)) {
      throw new BuildError(`${f}: 'date' is required and must be a valid YYYY-MM-DD date`);
    }
    const fmSlug = Object.hasOwn(meta, "slug") ? meta.slug : "";
    if (typeof fmSlug !== "string") throw new BuildError(`${f}: 'slug' must be a string`);
    const tags = Object.hasOwn(meta, "tags") ? meta.tags : [];
    if (!Array.isArray(tags) || !tags.every((t) => typeof t === "string")) {
      throw new BuildError(`${f}: 'tags' must be a list of strings`);
    }
    const summary = Object.hasOwn(meta, "summary") ? meta.summary : "";
    if (typeof summary !== "string") throw new BuildError(`${f}: 'summary' must be a string`);
    const slug = uniqueSlug(fmSlug ? fmSlug : title, taken);
    taken.add(slug);
    posts.push({
      map: {
        title,
        slug,
        date,
        tags: [...(tags as string[])],
        summary,
        url: `/posts/${slug}/`,
        content: markdown.render(body),
        tag_links: [],
      },
      body,
      tagSlugs: [],
    });
  }

  // tags (posts are still in filename order here)
  const tagMap = new Map<string, Obj>();
  for (const p of posts) {
    const seen: string[] = [];
    for (const t of p.map.tags as string[]) {
      const ts = slugify(t);
      if (ts === "") continue;
      if (!tagMap.has(ts)) tagMap.set(ts, { name: t, slug: ts, url: `/tags/${ts}/`, count: 0 });
      if (!seen.includes(ts)) {
        seen.push(ts);
        const tm = tagMap.get(ts)!;
        tm.count = (tm.count as number) + 1;
      }
    }
    p.tagSlugs = seen;
    p.map.tag_links = seen.map((ts) => {
      const tm = tagMap.get(ts)!;
      return { name: tm.name, slug: ts, url: tm.url };
    });
  }

  posts.sort(
    (a, b) => cmp(b.map.date as string, a.map.date as string) || cmp(a.map.slug as string, b.map.slug as string),
  );
  const tagList = [...tagMap.keys()].sort(cmp).map((k) => tagMap.get(k)!);

  const generated = new Map<string, string>();
  const pubPosts = posts.map((p) => p.map);
  generated.set(
    "index.html",
    renderTpl(tpl.index.p, tpl.index.text, { site, posts: pubPosts, tags: tagList }),
  );
  for (const p of posts) {
    generated.set(
      `posts/${p.map.slug as string}/index.html`,
      renderTpl(tpl.post.p, tpl.post.text, { site, post: p.map }),
    );
  }
  for (const t of tagList) {
    const tposts = posts.filter((p) => p.tagSlugs.includes(t.slug as string)).map((p) => p.map);
    generated.set(
      `tags/${t.slug as string}/index.html`,
      renderTpl(tpl.tag.p, tpl.tag.text, { site, tag: t, posts: tposts }),
    );
  }
  try {
    generated.set(
      "feed.xml",
      buildRss(
        site as { title: string; url: string; [k: string]: Value },
        posts.map((p) => ({
          title: p.map.title as string,
          url: p.map.url as string,
          date: p.map.date as string,
          summary: p.map.summary as string,
        })),
      ),
    );
    const docs = posts.map((p) => ({
      slug: p.map.slug as string,
      title: p.map.title as string,
      text: p.body,
    }));
    generated.set("search.json", stableJson(buildIndex(docs)));
  } catch (e) {
    if (e instanceof ValueError) throw new BuildError(`cannot build feed/search: ${e.message}`, { cause: e });
    throw e;
  }

  const staticDir = path.join(src, "static");
  const statics = new Map<string, string>();
  if (isDir(staticDir)) {
    try {
      walkStatic(staticDir, "", statics);
    } catch (e) {
      throw new BuildError(`${staticDir}: ${msg(e)}`, { cause: e });
    }
    for (const [rel, fp] of statics) {
      if (generated.has(rel)) {
        throw new BuildError(`${fp}: static file collides with generated file ${rel}`);
      }
    }
  }

  try {
    fs.mkdirSync(out, { recursive: true });
    for (const [rel, data] of generated) {
      const dest = path.join(out, ...rel.split("/"));
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.writeFileSync(dest, Buffer.from(data, "utf8"));
    }
    for (const [rel, fp] of statics) {
      const dest = path.join(out, ...rel.split("/"));
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.writeFileSync(dest, fs.readFileSync(fp));
    }
  } catch (e) {
    throw new BuildError(`${out}: cannot write output: ${msg(e)}`, { cause: e });
  }

  return {
    posts: posts.length,
    drafts,
    tagPages: tagList.length,
    staticFiles: statics.size,
    outputFiles: [...generated.keys(), ...statics.keys()].sort(cmp),
  };
}

export { SitegenError };
