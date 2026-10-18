import { ValueError } from "./errors.js";
import type { Value } from "./frontmatter.js";
import { cmp, isValidDate } from "./util.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function x(s: string): string {
  return s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function buildRss(
  site: { title: string; url: string; [k: string]: Value },
  posts: { title: string; url: string; date: string; summary?: string }[],
): string {
  if (!isObj(site)) throw new ValueError("site must be an object");
  for (const key of ["title", "url"]) {
    if (typeof site[key] !== "string") throw new ValueError(`site needs string ${key}`);
  }
  if (!Array.isArray(posts)) throw new ValueError("posts must be a list");
  for (const post of posts) {
    const p: unknown = post;
    if (!isObj(p)) throw new ValueError("post must be an object");
    for (const key of ["title", "url", "date"]) {
      if (typeof p[key] !== "string") throw new ValueError(`post needs string ${key}`);
    }
    if (!isValidDate(p.date)) throw new ValueError(`invalid date: ${String(p.date)}`);
    if (p.summary !== undefined && typeof p.summary !== "string") {
      throw new ValueError("post summary must be a string");
    }
  }
  const ordered = [...posts]
    .sort((a, b) => cmp(b.date, a.date) || cmp(a.url, b.url))
    .slice(0, 20);
  const base = site.url.replace(/\/+$/, "");
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss version="2.0">',
    "<channel>",
    `<title>${x(site.title)}</title>`,
    `<link>${x(base + "/")}</link>`,
    `<description>${x(site.title)}</description>`,
  ];
  for (const p of ordered) {
    const y = Number(p.date.slice(0, 4));
    const mo = Number(p.date.slice(5, 7));
    const d = Number(p.date.slice(8, 10));
    const dt = new Date(0);
    dt.setUTCFullYear(y, mo - 1, d);
    const link = base + "/" + p.url.replace(/^\/+/, "");
    const pub = `${DAYS[(dt.getUTCDay() + 6) % 7]}, ${String(d).padStart(2, "0")} ${MONTHS[mo - 1]} ${String(y).padStart(4, "0")} 00:00:00 +0000`;
    lines.push(
      "<item>",
      `<title>${x(p.title)}</title>`,
      `<link>${x(link)}</link>`,
      `<guid>${x(link)}</guid>`,
      `<pubDate>${pub}</pubDate>`,
      `<description>${x(p.summary ?? "")}</description>`,
      "</item>",
    );
  }
  lines.push("</channel>", "</rss>");
  return lines.join("\n");
}
