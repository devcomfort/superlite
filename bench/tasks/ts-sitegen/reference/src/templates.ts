import { TemplateError } from "./errors.js";
import type { Value } from "./frontmatter.js";

export function esc(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
}

type V = Value | undefined;

interface Filter {
  name: string;
  arg: string | null;
}
interface Expr {
  path: string[];
  filters: Filter[];
}
interface Cond {
  negate: boolean;
  expr: Expr;
}
type Node =
  | { t: "text"; text: string }
  | { t: "var"; expr: Expr }
  | { t: "if"; branches: { cond: Cond; body: Node[] }[]; elseBody: Node[] | null }
  | { t: "for"; name: string; expr: Expr; body: Node[] };

const NAME = "[A-Za-z_][A-Za-z0-9_]*";
const PATH = new RegExp(`^${NAME}(?:\\.(?:${NAME}|[0-9]+))*`);
const FILTER_NAME = /^[a-z]+/;
const NOT = /^not\s+([\s\S]*)$/;
const IF = /^(if|elif)\s+([\s\S]*)$/;
const FOR = new RegExp(`^for\\s+(${NAME})\\s+in\\s+([\\s\\S]*)$`);
const FILTERS: Record<string, boolean> = {
  upper: false,
  lower: false,
  title: false,
  escape: false,
  safe: false,
  default: true,
  join: true,
  length: false,
};

function isSpace(c: string): boolean {
  return /\s/.test(c);
}

function parseExpr(src: string): Expr {
  const m = PATH.exec(src);
  if (!m) throw new TemplateError(`invalid expression: ${JSON.stringify(src)}`);
  const path = m[0].split(".");
  let i = m[0].length;
  const n = src.length;
  const filters: Filter[] = [];
  for (;;) {
    while (i < n && isSpace(src[i])) i++;
    if (i >= n) break;
    if (src[i] !== "|") throw new TemplateError(`invalid expression: ${JSON.stringify(src)}`);
    i++;
    while (i < n && isSpace(src[i])) i++;
    const fm = FILTER_NAME.exec(src.slice(i));
    if (!fm) throw new TemplateError(`invalid filter in: ${JSON.stringify(src)}`);
    const name = fm[0];
    i += name.length;
    if (i < n && !(isSpace(src[i]) || src[i] === ":" || src[i] === "|")) {
      throw new TemplateError(`invalid filter in: ${JSON.stringify(src)}`);
    }
    while (i < n && isSpace(src[i])) i++;
    let arg: string | null = null;
    if (i < n && src[i] === ":") {
      i++;
      while (i < n && isSpace(src[i])) i++;
      if (i >= n || (src[i] !== '"' && src[i] !== "'")) {
        throw new TemplateError(`invalid filter argument in: ${JSON.stringify(src)}`);
      }
      const q = src[i];
      const j = src.indexOf(q, i + 1);
      if (j === -1) throw new TemplateError(`unterminated filter argument in: ${JSON.stringify(src)}`);
      arg = src.slice(i + 1, j);
      i = j + 1;
    }
    if (!Object.hasOwn(FILTERS, name)) throw new TemplateError(`unknown filter: ${name}`);
    if (FILTERS[name] && arg === null) throw new TemplateError(`filter ${name} requires an argument`);
    if (!FILTERS[name] && arg !== null) throw new TemplateError(`filter ${name} takes no argument`);
    filters.push({ name, arg });
  }
  return { path, filters };
}

function parseCond(src: string): Cond {
  let negate = false;
  const m = NOT.exec(src);
  if (m) {
    negate = true;
    src = m[1].trim();
  }
  return { negate, expr: parseExpr(src) };
}

type Token = { kind: "text" | "var" | "stmt"; val: string };

function tokenize(template: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  const n = template.length;
  while (i < n) {
    const a = template.indexOf("{{", i);
    const b = template.indexOf("{%", i);
    const cands = [a, b].filter((x) => x !== -1);
    if (cands.length === 0) {
      tokens.push({ kind: "text", val: template.slice(i) });
      break;
    }
    const s = Math.min(...cands);
    if (s > i) tokens.push({ kind: "text", val: template.slice(i, s) });
    let e: number;
    let kind: "var" | "stmt";
    if (s === a) {
      e = template.indexOf("}}", s + 2);
      kind = "var";
    } else {
      e = template.indexOf("%}", s + 2);
      kind = "stmt";
    }
    if (e === -1) throw new TemplateError("unclosed tag");
    tokens.push({ kind, val: template.slice(s + 2, e).trim() });
    i = e + 2;
  }
  return tokens;
}

type Term = { name: string; cond?: Cond };

function parseTemplate(template: string): Node[] {
  const tokens = tokenize(template);
  let pos = 0;

  function block(terms: Set<string>): [Node[], Term | null] {
    const nodes: Node[] = [];
    while (pos < tokens.length) {
      const { kind, val } = tokens[pos++];
      if (kind === "text") {
        nodes.push({ t: "text", text: val });
      } else if (kind === "var") {
        nodes.push({ t: "var", expr: parseExpr(val) });
      } else {
        if (val === "else" || val === "endif" || val === "endfor") {
          if (terms.has(val)) return [nodes, { name: val }];
          throw new TemplateError(`unexpected ${val}`);
        }
        const m = IF.exec(val);
        if (m) {
          const cond = parseCond(m[2].trim());
          if (m[1] === "elif") {
            if (terms.has("elif")) return [nodes, { name: "elif", cond }];
            throw new TemplateError("unexpected elif");
          }
          nodes.push(parseIf(cond));
          continue;
        }
        const f = FOR.exec(val);
        if (f) {
          const expr = parseExpr(f[2].trim());
          const [body] = block(new Set(["endfor"]));
          nodes.push({ t: "for", name: f[1], expr, body });
          continue;
        }
        throw new TemplateError(`unknown statement: ${JSON.stringify(val)}`);
      }
    }
    if (terms.size > 0) throw new TemplateError("unclosed block");
    return [nodes, null];
  }

  function parseIf(first: Cond): Node {
    const branches: { cond: Cond; body: Node[] }[] = [];
    let elseBody: Node[] | null = null;
    let cond = first;
    for (;;) {
      const [body, term] = block(new Set(["elif", "else", "endif"]));
      branches.push({ cond, body });
      if (term!.name === "endif") break;
      if (term!.name === "elif") {
        cond = term!.cond!;
        continue;
      }
      [elseBody] = block(new Set(["endif"]));
      break;
    }
    return { t: "if", branches, elseBody };
  }

  const [nodes] = block(new Set());
  return nodes;
}

function isMap(v: unknown): v is { [k: string]: Value } {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function lookup(path: string[], scopes: Map<string, Value>[], context: Record<string, Value>): V {
  const first = path[0];
  let cur: V = undefined;
  let found = false;
  for (let k = scopes.length - 1; k >= 0; k--) {
    if (scopes[k].has(first)) {
      cur = scopes[k].get(first);
      found = true;
      break;
    }
  }
  if (!found && Object.hasOwn(context, first)) cur = context[first];
  for (let k = 1; k < path.length; k++) {
    const seg = path[k];
    if (isMap(cur)) {
      cur = Object.hasOwn(cur, seg) ? cur[seg] : undefined;
    } else if (Array.isArray(cur) && /^[0-9]+$/.test(seg)) {
      const idx = Number(seg);
      cur = idx < cur.length ? cur[idx] : undefined;
    } else {
      return undefined;
    }
  }
  return cur;
}

function text(v: V): string {
  if (v === undefined || v === null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function titleCase(s: string): string {
  return s.replace(/\p{L}+/gu, (run) => {
    const chars = Array.from(run);
    return chars[0].toUpperCase() + chars.slice(1).join("").toLowerCase();
  });
}

function cpLength(s: string): number {
  return Array.from(s).length;
}

function apply(value: V, filters: Filter[]): { value: V; safe: boolean } {
  let safe = false;
  for (const { name, arg } of filters) {
    switch (name) {
      case "upper":
        value = text(value).toUpperCase();
        break;
      case "lower":
        value = text(value).toLowerCase();
        break;
      case "title":
        value = titleCase(text(value));
        break;
      case "escape":
        value = esc(text(value));
        safe = true;
        break;
      case "safe":
        safe = true;
        break;
      case "default":
        if (value === undefined || value === null || value === "") {
          value = arg!;
          safe = false;
        }
        break;
      case "join":
        if (Array.isArray(value)) value = value.map((x) => text(x)).join(arg!);
        else value = text(value);
        safe = false;
        break;
      case "length":
        if (value === undefined || value === null) value = 0;
        else if (typeof value === "string") value = cpLength(value);
        else if (Array.isArray(value)) value = value.length;
        else if (isMap(value)) value = Object.keys(value).length;
        else value = cpLength(text(value));
        break;
    }
  }
  return { value, safe };
}

function truthy(v: V): boolean {
  if (v === undefined || v === null || v === false || v === 0 || v === "") return false;
  if (Array.isArray(v)) return v.length > 0;
  if (isMap(v)) return Object.keys(v).length > 0;
  return true;
}

function evalExpr(expr: Expr, scopes: Map<string, Value>[], context: Record<string, Value>) {
  return apply(lookup(expr.path, scopes, context), expr.filters);
}

function run(
  nodes: Node[],
  scopes: Map<string, Value>[],
  context: Record<string, Value>,
  out: string[],
): void {
  for (const node of nodes) {
    if (node.t === "text") {
      out.push(node.text);
    } else if (node.t === "var") {
      const { value, safe } = evalExpr(node.expr, scopes, context);
      const s = text(value);
      out.push(safe ? s : esc(s));
    } else if (node.t === "if") {
      let done = false;
      for (const { cond, body } of node.branches) {
        const { value } = evalExpr(cond.expr, scopes, context);
        if (truthy(value) !== cond.negate) {
          run(body, scopes, context, out);
          done = true;
          break;
        }
      }
      if (!done && node.elseBody !== null) run(node.elseBody, scopes, context, out);
    } else {
      const { value } = evalExpr(node.expr, scopes, context);
      let items: Value[] = [];
      if (Array.isArray(value)) items = [...value];
      else if (isMap(value)) items = Object.keys(value);
      const total = items.length;
      for (let idx = 0; idx < total; idx++) {
        const scope = new Map<string, Value>();
        scope.set(node.name, items[idx]);
        scope.set("loop", {
          index: idx + 1,
          index0: idx,
          first: idx === 0,
          last: idx === total - 1,
          length: total,
        });
        scopes.push(scope);
        try {
          run(node.body, scopes, context, out);
        } finally {
          scopes.pop();
        }
      }
    }
  }
}

export function render(template: string, context: Record<string, Value>): string {
  const nodes = parseTemplate(template);
  const out: string[] = [];
  run(nodes, [], context, out);
  return out.join("");
}
