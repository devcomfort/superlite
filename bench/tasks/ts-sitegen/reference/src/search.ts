import { ValueError } from "./errors.js";
import { cmp, setOwn } from "./util.js";

export const STOPWORDS: ReadonlySet<string> = new Set(
  "a an and are as at be by for from in is it of on or that the to with".split(" "),
);

export interface SearchIndex {
  docs: Record<string, { title: string; length: number }>;
  terms: Record<string, Record<string, number>>;
}

export function tokenize(s: string): string[] {
  return (s.toLowerCase().match(/[a-z0-9]+/g) ?? []).filter((t) => !STOPWORDS.has(t));
}

export function buildIndex(docs: { slug: string; title: string; text: string }[]): SearchIndex {
  const per = new Map<string, { title: string; counts: Map<string, number>; length: number }>();
  for (const d of docs) {
    if (typeof d !== "object" || d === null) throw new ValueError("doc must be an object");
    for (const key of ["slug", "title", "text"] as const) {
      if (typeof d[key] !== "string") throw new ValueError(`doc needs string ${key}`);
    }
    if (per.has(d.slug)) throw new ValueError(`duplicate slug: ${d.slug}`);
    const tokens = [...tokenize(d.title), ...tokenize(d.text)];
    const counts = new Map<string, number>();
    for (const t of tokens) counts.set(t, (counts.get(t) ?? 0) + 1);
    per.set(d.slug, { title: d.title, counts, length: tokens.length });
  }
  const slugs = [...per.keys()].sort(cmp);
  const terms = new Map<string, Map<string, number>>();
  for (const slug of slugs) {
    for (const [term, tf] of per.get(slug)!.counts) {
      let m = terms.get(term);
      if (!m) terms.set(term, (m = new Map()));
      m.set(slug, tf);
    }
  }
  const index: SearchIndex = { docs: {}, terms: {} };
  for (const slug of slugs) {
    const p = per.get(slug)!;
    setOwn(index.docs, slug, { title: p.title, length: p.length });
  }
  for (const t of [...terms.keys()].sort(cmp)) {
    const po: Record<string, number> = {};
    for (const [s, tf] of terms.get(t)!) setOwn(po, s, tf);
    setOwn(index.terms, t, po);
  }
  return index;
}

export function search(index: SearchIndex, query: string, limit = 10): string[] {
  const terms = [...new Set(tokenize(query))];
  if (terms.length === 0 || limit <= 0) return [];
  const postings = index.terms ?? {};
  let candidates: Set<string> = new Set();
  let firstTerm = true;
  for (const t of terms) {
    const p = Object.hasOwn(postings, t) ? postings[t] : undefined;
    if (!p || Object.keys(p).length === 0) return [];
    const keys = Object.keys(p);
    const prev = candidates;
    candidates = firstTerm ? new Set(keys) : new Set(keys.filter((k) => prev.has(k)));
    firstTerm = false;
  }
  const scored = [...candidates].map((s) => {
    let score = 0;
    for (const t of terms) score += postings[t][s];
    return { s, score };
  });
  scored.sort((a, b) => b.score - a.score || cmp(a.s, b.s));
  return scored.slice(0, limit).map((e) => e.s);
}
