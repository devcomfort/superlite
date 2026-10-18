import { ValueError } from "./errors.js";
import { cmp } from "./util.js";

const A_TAG = /<a\s[^>]*>/gi;
const HREF = /(?<![\w-])href\s*=\s*(?:"([^"]*)"|'([^']*)')/i;
const ID = /(?<![\w-])id\s*=\s*(?:"([^"]*)"|'([^']*)')/gi;
const SCHEME = /^[A-Za-z][A-Za-z0-9+.-]*:/;

function val(m: RegExpMatchArray | RegExpExecArray): string {
  return m[1] !== undefined ? m[1] : m[2];
}

function resolve(page: string, rest: string): [string, boolean] {
  const joined = rest.startsWith("/") ? rest : page.slice(0, page.lastIndexOf("/") + 1) + rest;
  const segs: string[] = [];
  for (const seg of joined.split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") {
      segs.pop();
      continue;
    }
    segs.push(seg);
  }
  const result = "/" + segs.join("/");
  const parts = joined.split("/");
  const last = parts[parts.length - 1];
  const directory = joined.endsWith("/") || last === "." || last === ".." || segs.length === 0;
  return [result, directory];
}

export function findBrokenLinks(pages: Record<string, string>): [string, string][] {
  const keys = Object.keys(pages);
  for (const key of keys) {
    if (!key.startsWith("/")) throw new ValueError(`page path must start with '/': ${key}`);
  }
  const has = (k: string): boolean => Object.hasOwn(pages, k);
  const ids = new Map<string, Set<string>>();
  for (const path of keys) {
    if (path.endsWith(".html")) {
      ids.set(path, new Set([...pages[path].matchAll(ID)].map((m) => val(m))));
    }
  }
  const broken: [string, string][] = [];
  for (const page of [...keys].sort(cmp)) {
    if (!page.endsWith(".html")) continue;
    for (const tag of pages[page].matchAll(A_TAG)) {
      const hm = HREF.exec(tag[0]);
      if (!hm) continue;
      const href = val(hm).trim();
      if (href === "" || href.startsWith("//") || SCHEME.test(href)) continue;
      const hash = href.indexOf("#");
      let rest = hash === -1 ? href : href.slice(0, hash);
      const frag = hash === -1 ? "" : href.slice(hash + 1);
      const q = rest.indexOf("?");
      if (q !== -1) rest = rest.slice(0, q);
      let target: string;
      if (rest === "") {
        target = page;
      } else {
        const [result, directory] = resolve(page, rest);
        if (directory) {
          target = result.replace(/\/+$/, "") + "/index.html";
        } else {
          target = result;
          if (!has(target) && has(result + "/index.html")) target = result + "/index.html";
        }
      }
      if (!has(target)) {
        broken.push([page, href]);
        continue;
      }
      if (frag !== "") {
        const s = ids.get(target);
        if (!(s && s.has(frag))) broken.push([page, href]);
      }
    }
  }
  return broken;
}
