import { describe, expect, test } from "vitest";
import { TemplateError } from "../src/errors.js";
import { render } from "../src/templates.js";

const T = (t: string, ctx: Record<string, any> = {}) => render(t, ctx);
const raises = (t: string, ctx: Record<string, any> = {}) =>
  expect(() => T(t, ctx)).toThrow(TemplateError);

describe("templates", () => {
  test("simple variable", () => {
    expect(T("Hello {{ name }}!", { name: "World" })).toBe("Hello World!");
  });
  test("autoescape and safe filter", () => {
    const x = `<a href="u">&'`;
    expect(T("{{ x }}", { x })).toBe("&lt;a href=&quot;u&quot;&gt;&amp;&#x27;");
    expect(T("{{ x|safe }}", { x })).toBe(x);
  });
  test("escape filter not double escaped", () => {
    expect(T("{{ s|escape }}", { s: "<b>" })).toBe("&lt;b&gt;");
  });
  test("undefined and null render empty", () => {
    expect(T("[{{ missing }}][{{ a.b.c }}][{{ n }}]", { a: { b: {} }, n: null })).toBe("[][][]");
  });
  test("case filters", () => {
    expect(T("{{ t|upper }} {{ t|lower }} {{ t|title }}", { t: "hello woRLD" })).toBe(
      "HELLO WORLD hello world Hello World",
    );
  });
  test("join and length filters", () => {
    const ctx = { tags: ["a", "b"] };
    expect(T('{{ tags|join:", " }} / {{ tags|length }}', ctx)).toBe("a, b / 2");
    expect(T('{{ tags|join:" | "|safe }}', ctx)).toBe("a | b");
  });
  test("default filter", () => {
    const t = '{{ nick|default:"anon" }}';
    expect(T(t, {})).toBe("anon");
    expect(T(t, { nick: "" })).toBe("anon");
    expect(T(t, { nick: 0 })).toBe("0");
  });
  test("for loop with loop variables", () => {
    const t = "{% for t in tags %}{{ loop.index }}:{{ t }}{% if not loop.last %}, {% endif %}{% endfor %}";
    expect(T(t, { tags: ["a", "b"] })).toBe("1:a, 2:b");
  });
  test("bad if expression raises", () => {
    raises("{% if n > 1 %}x{% endif %}");
  });
  test.each([
    "{{ a|bogus }}",
    "{{ name",
    "{% for x in y %}no end",
    "{% endif %}",
    "{% if a %}{% else %}{% else %}{% endif %}",
  ])("spec syntax error raises TemplateError: %s", (t) => {
    raises(t, { a: 1 });
  });
  test.each([
    "{{ }}",
    "{{ 1a }}",
    "{% unknown %}",
    "{% for k, v in x %}{% endfor %}",
    "{% if a %}x",
    "{% endfor %}",
    "{% else %}",
    "{% elif a %}",
    "{% if a %}{% else %}{% elif b %}{% endif %}",
    "{% if a %}{% for x in y %}{% endif %}{% endfor %}",
    '{{ a|upper:"x" }}',
    "{{ a|default }}",
    "{{ a|join }}",
    "{% endif x %}",
    "{% else x %}",
    '{{ "lit" }}',
  ])("more invalid templates raise: %s", (t) => {
    raises(t, { a: 1 });
  });
  test("error in unexecuted branch still raises", () => {
    raises("{% if a %}x{% else %}{{ b|bogus }}{% endif %}", { a: true });
  });
  test("if elif else", () => {
    const t = "{% if a %}A{% elif b %}B{% else %}C{% endif %}";
    expect(T(t, { a: 0, b: [1] })).toBe("B");
    expect(T(t, { a: 0, b: [] })).toBe("C");
  });
  test("no whitespace trimming", () => {
    const t = "{% if x %}\nA\n{% endif %}\n";
    expect(T(t, { x: true })).toBe("\nA\n\n");
    expect(T(t, { x: false })).toBe("\n");
  });
  test("for over posts and nothing", () => {
    const t = "{% for p in posts %}{{ p.title }}{% endfor %}|{% for p in nothing %}x{% endfor %}";
    expect(T(t, { posts: [{ title: "T1" }, { title: "T2" }] })).toBe("T1T2|");
  });
  test("empty template and list index", () => {
    expect(T("")).toBe("");
    expect(T("{{ items.0 }}-{{ items.5 }}", { items: ["z"] })).toBe("z-");
  });
  test("context not mutated and loop var scoped to body", () => {
    const ctx = { x: "outer", xs: [1, 2] };
    const out = T("{% for x in xs %}{{ x }}{% endfor %}{{ x }}{{ loop }}", ctx);
    expect(out).toBe("12outer");
    expect(ctx).toEqual({ x: "outer", xs: [1, 2] });
  });
});
