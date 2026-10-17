# sitegen: product specification

Build `sitegen-core`, the core library of a static site generator, from scratch. (Sections 6, 8, 9 and 10 of the full product are not part of this task.) This SPEC is the complete public contract; a hidden acceptance suite checks it exactly. Where a rule or example is given, follow it literally. "MUST" = tested.

## 0. Project setup

- Python >= 3.12, **stdlib only at runtime** (no third-party runtime dependencies). `uv` project: `pyproject.toml` with `name = "sitegen"`, `requires-python = ">=3.12"`, `dependencies = []`, a `[build-system]` so that `uv run` installs the package, and a dev dependency group containing `pytest`.
- Src layout: `src/sitegen/` containing `__init__.py` (may be empty), `errors.py`, `frontmatter.py`, `markdown.py`, `templates.py`, `slug.py`, `search.py`. Your own tests go in `tests/`.
- Command that MUST work from the project root: `uv run pytest`.
- Conventions: all text is UTF-8; generated files use `\n` newlines and are written byte-exact from the returned/rendered strings (no added trailing newline). Output is deterministic (no timestamps). Functions taking paths accept `str` or `os.PathLike`.
- HTML escape (`esc`) used by markdown, templates and the pages: replace `&`->`&amp;` `<`->`&lt;` `>`->`&gt;` `"`->`&quot;` `'`->`&#x27;` (same as `html.escape(s, quote=True)`).

## 1. errors.py

```python
class SitegenError(Exception): ...
class FrontmatterError(SitegenError, ValueError): ...
class TemplateError(SitegenError): ...
class BuildError(SitegenError): ...
```

Other invalid-argument cases below raise plain `ValueError`.

## 2. frontmatter.py

`parse(text: str) -> tuple[dict, str]` returns `(metadata, body)`.

Rules:
1. First normalize every `\r\n` in `text` to `\n`.
2. If the first line is not exactly `---`: return `({}, text)` (normalized text).
3. Otherwise the block ends at the next line that is exactly `---`. No closing line -> `FrontmatterError`. `body` is everything after the closing line's `\n`, verbatim (no stripping); if the closing line is last with no `\n`, body is `""`.
4. Inside the block: lines that are empty/whitespace-only, or whose first non-space char is `#`, are ignored. Every other line MUST match `^([A-Za-z_][A-Za-z0-9_-]*):(?: +(.*))?$` (no leading indentation) else `FrontmatterError`. Duplicate key -> `FrontmatterError`. Keys keep insertion order.
5. The value is stripped, then interpreted:
   - empty -> `""`
   - starts with `"`: double-quoted string; MUST end with the closing unescaped `"` and nothing after it. Escapes: `\"` `\\` `\n` `\t`; any other backslash sequence -> `FrontmatterError`. Unterminated -> `FrontmatterError`.
   - starts with `'`: single-quoted; `''` is a literal `'`; no other escapes; MUST terminate with nothing after it, else `FrontmatterError`.
   - starts with `[`: inline list. MUST end with `]` else `FrontmatterError`. Inner text empty/whitespace -> `[]`. Otherwise items are separated by commas outside quotes; items are stripped; a quoted item is parsed as above (commas and `]` allowed inside quotes); an unquoted item is parsed by the scalar rules below (bool/int/plain). An empty item (`[a,,b]`, `[a,]`) or a nested `[` -> `FrontmatterError`.
   - exactly `true` / `false` -> `True` / `False` (case-sensitive; `True`, `yes` are plain strings)
   - matches `^[+-]?[0-9]+$` -> `int` (`007` -> 7, `-5` -> -5)
   - otherwise a plain string (the stripped text). No inline `#` comments (kept literally); `null`, `~`, floats and dates stay strings; `a: b: c` -> `"b: c"`.

Examples:
| input | output |
|---|---|
| `"hello"` | `({}, "hello")` |
| `"---\ntitle: Hi\n---\nBody\n"` | `({"title": "Hi"}, "Body\n")` |
| `"---\r\ntitle: Hi\r\n---\r\nB"` | `({"title": "Hi"}, "B")` |
| `"---\nn: 42\nok: true\nno: false\ns: \"a: b\"\nt: 'it''s'\n---\n"` | `({"n": 42, "ok": True, "no": False, "s": "a: b", "t": "it's"}, "")` |
| `"---\ntags: [a, \"b, c\", 3, true]\nempty: []\ne:\n---\nx"` | `({"tags": ["a", "b, c", 3, True], "empty": [], "e": ""}, "x")` |
| `"---\n# note\n\ndate: 2024-01-15\nslug: -x\n---\n\n\nbody"` | `({"date": "2024-01-15", "slug": "-x"}, "\n\nbody")` |
| `"---\n---\nbody"` | `({}, "body")` |
| `"---\ntitle: x\n"` | raises `FrontmatterError` |
| `"---\ntitle x\n---\n"`, `"---\na: 1\na: 2\n---\n"`, `"---\na: [1,\n---\n"` | raise `FrontmatterError` |

## 3. markdown.py

`render(md: str) -> str`. Input `\r\n` -> `\n` first. Output = block HTML strings joined with `"\n"`, **no trailing newline**. Empty or whitespace-only input -> `""`. Every line is right-stripped (trailing whitespace removed) before block detection, except lines inside fenced code (kept verbatim). Blank = empty after strip.

### Blocks (checked per line in this priority; markers must start at column 0; an indented line is paragraph text)
1. **Fenced code**: a line starting with ```` ``` ````. Info string = rest of line stripped; language = its first whitespace-delimited token (if any). Closes at the next line that equals ```` ``` ```` after right-strip; unclosed -> runs to end of input. Output `<pre><code>` + escaped lines joined by `\n` + `</code></pre>`; with a language `<pre><code class="language-LANG">` (LANG escaped). No trailing newline inside; empty fence -> `<pre><code></code></pre>`.
2. **Heading**: matches `^(#{1,6}) +(.+)$` -> `<hN>inline</hN>`. No ids. No closing-`#` handling (kept literally). `#x`, `####### x` and a bare `#` are paragraphs.
3. **HR**: matches `^(?:-{3,}|\*{3,}|_{3,})$` -> `<hr>`. (No setext headings: `---` after text is an hr and ends the paragraph.)
4. **Blockquote**: consecutive lines starting with `>`; strip the `>` and one following space if present; join the remaining lines with `\n` and render recursively as markdown. Output `<blockquote>\n` + inner + `\n</blockquote>`; empty inner -> `<blockquote></blockquote>`. A line not starting with `>` ends it (no lazy continuation).
5. **Lists** (flat; no nesting): unordered item `^[-*+] +(.*)$`, ordered item `^[0-9]+\. +(.*)$`. Consecutive items of the same kind form one list; changing kind or a blank line starts a new list (no loose lists); a non-item line ends the list. Output `<ul>\n<li>x</li>\n<li>y</li>\n</ul>` (`<ol>` for ordered; the start number is ignored). Item text is inline-rendered, one line only.
6. **Paragraph**: consecutive non-blank lines that start no other block (a heading, fence, hr, blockquote or list item line interrupts a paragraph). Each line is stripped; lines joined with `\n` (soft breaks kept, no `<br>`); inline-rendered; `<p>...</p>`.

### Inline rendering (exactly this order)
1. **Code spans**: scan left-to-right for `` `([^`]+)` `` -> `<code>` + esc(content) + `</code>`. Content gets no other processing. Unmatched backticks are literal. Treat each span as an opaque placeholder (counts as a non-alphanumeric, non-space char for the rules below).
2. Escape everything else with `esc` (raw HTML never passes through; `&amp;` becomes `&amp;amp;`).
3. **Images** `!\[([^\]]*)\]\(([^)\s]+)\)` -> `<img src="URL" alt="ALT">`.
4. **Links** `\[([^\]]+)\]\(([^)\s]+)\)` -> `<a href="URL">TEXT</a>`. TEXT gets steps 5 below applied (emphasis); URL, `src` and `alt` are never emphasis-processed (so `a_b_c` in a URL is safe). URL/ALT are the already-escaped text. No title support, no URL filtering. Images and links are opaque placeholders for emphasis.
5. **Emphasis**, `re.sub` without DOTALL (cannot span a line break), applied in this order to the whole text:
   - `\*\*\*(?!\s)(.+?)(?<!\s)\*\*\*` -> `<strong><em>\1</em></strong>`
   - `\*\*(?!\s)(.+?)(?<!\s)\*\*` -> `<strong>\1</strong>`
   - `(?<![A-Za-z0-9])__(?!\s)(.+?)(?<!\s)__(?![A-Za-z0-9])` -> `<strong>\1</strong>`
   - `\*(?!\s)(.+?)(?<!\s)\*` -> `<em>\1</em>`
   - `(?<![A-Za-z0-9])_(?!\s)(.+?)(?<!\s)_(?![A-Za-z0-9])` -> `<em>\1</em>`
6. Restore placeholders. Backslash escapes, autolinks, hard breaks, reference links, titles are not supported (backslash is literal).

Examples (`md` -> output):
1. `# Hello` -> `<h1>Hello</h1>`
2. `Hello *world* and **bold**` -> `<p>Hello <em>world</em> and <strong>bold</strong></p>`
3. `a < b & "c" 'd'` -> `<p>a &lt; b &amp; &quot;c&quot; &#x27;d&#x27;</p>`
4. `<script>alert(1)</script>` -> `<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>`
5. `para one\nstill one\n\n\npara two\n` -> `<p>para one\nstill one</p>\n<p>para two</p>`
6. `- a\n- b\n\n1. x\n2. y` -> `<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n<ol>\n<li>x</li>\n<li>y</li>\n</ol>`
7. the 3-line text: fence-open line with `python`, line `print('<hi>')`, fence-close line (three backticks each) -> `<pre><code class="language-python">print(&#x27;&lt;hi&gt;&#x27;)</code></pre>`
8. `> quote *x*\n> more` -> `<blockquote>\n<p>quote <em>x</em>\nmore</p>\n</blockquote>`
9. `[a](http://x.com/a_b_c?q=1&r=2)` -> `<p><a href="http://x.com/a_b_c?q=1&amp;r=2">a</a></p>`
10. `![alt](/i.png)` -> `<p><img src="/i.png" alt="alt"></p>`
11. `***bold italic***` -> `<p><strong><em>bold italic</em></strong></p>`
12. `**bold with *nested em* inside** and *em with **strong** inside*` -> `<p><strong>bold with <em>nested em</em> inside</strong> and <em>em with <strong>strong</strong> inside</em></p>`
13. ``use `a<b` and snake_case_name, 2 * 3 * 4`` -> `<p>use <code>a&lt;b</code> and snake_case_name, 2 * 3 * 4</p>`
14. `---` -> `<hr>`; the empty string and `"\n\n  \n"` -> the empty string `""`
15. `- a\n\n- b` -> `<ul>\n<li>a</li>\n</ul>\n<ul>\n<li>b</li>\n</ul>`
16. `## Title\ntext\n---\nmore` -> `<h2>Title</h2>\n<p>text</p>\n<hr>\n<p>more</p>`

## 4. templates.py

`render(template: str, context: dict) -> str`. Raises `TemplateError` on any syntax/semantic error listed below. The **whole template is parsed and validated before any output**, so errors in unexecuted branches still raise. `context` is not mutated.

### Syntax
- Text outside tags is copied verbatim. **No whitespace trimming of any kind** (no `{%-`); newlines around tags are output as written.
- Tags: `{{ expr }}` and `{% stmt %}`. A tag ends at the FIRST `}}` / `%}` after its opener, even inside a quoted string. Inner text is stripped. An opener with no closer -> `TemplateError`. A lone `{`, `}`, or `{#` is literal text. No comments, no escaping of `{{`.
- `expr` = `path` followed by zero or more `| filter`. `path` = `NAME(.SEG)*`, NAME `[A-Za-z_][A-Za-z0-9_]*`, SEG = NAME or `[0-9]+`. Anything else (empty `{{ }}`, `{{ 1a }}`, literals as base) -> `TemplateError`.
- A filter is `name` or `name:ARG` (whitespace allowed around `|` and `:`); ARG is a string in `"..."` or `'...'` with no escapes (ends at the first matching quote; may contain `|`, `:`, spaces). Filters are lowercase names matching `[a-z]+`.
- Statements: `if EXPR_C`, `elif EXPR_C`, `else`, `endif`, `for NAME in EXPR`, `endfor`. `EXPR_C` = `expr` or `not expr` (`not` then whitespace). `else`/`endif`/`endfor` take no arguments. Unknown statement, unbalanced/misnested blocks, `elif`/`else` after `else`, `elif`/`else`/`endif`/`endfor` outside their block, tuple loops (`for k, v in x`) -> `TemplateError`.

### Semantics
- **Lookup**: first segment is searched in the loop scopes (innermost first), then `context`. For each later segment: current is `dict` -> key lookup (string key); current is `list`/`tuple` and SEG is digits -> index; anything else, missing key, or out of range -> *undefined*. A key present with value `None` is defined (value `None`).
- **Output** of `{{ }}`: undefined and `None` -> `""`; `str` as is; otherwise Python `str(value)` (`True` -> `True`, `5` -> `5`, lists via `str(list)`). Unless the value is marked safe, the resulting text is passed through `esc`. **Undefined never raises.**
- **Truthiness**: Python truthiness; undefined is false.
- **Filters** (value flows left to right together with a safe flag; context values start unsafe):
  - `upper`, `lower`, `title` (`str.title()`): apply to `str(value)` (undefined/None -> `""`); safe flag preserved.
  - `escape`: `esc(str(value))`, marked safe (so never double-escaped). `safe`: marks safe, value unchanged.
  - `default:"x"`: if the value is undefined, `None`, or `""` -> the literal `x` (unsafe); otherwise unchanged (`0`, `False`, `[]` are kept).
  - `join:", "`: for a `list`/`tuple` -> `str(item)` of each joined by the ARG (result unsafe); undefined/None -> `""`; any other value -> `str(value)`.
  - `length`: `len()` for str/list/tuple/dict; undefined/None -> 0; other values `len(str(value))`.
  - Unknown filter, missing ARG for `default`/`join`, ARG given to any other filter -> `TemplateError`.
- **for**: list/tuple iterate elements; dict iterates keys; anything else (undefined, None, str, numbers) -> zero iterations. The loop variable and `loop` exist only inside the body (outer values restored after; nested loops shadow `loop`). `loop` is a dict: `index` (1-based), `index0`, `first` (bool), `last` (bool), `length`.
- **if/elif/else**: first branch whose condition is truthy renders; else the `else` body; otherwise nothing.

Examples (`template` | context -> output):
1. `Hello {{ name }}!` | `{"name": "World"}` -> `Hello World!`
2. `{{ x }}` | `x = '<a href="u">&\''` -> `&lt;a href=&quot;u&quot;&gt;&amp;&#x27;`; `{{ x|safe }}` -> the raw text unchanged
3. `{{ s|escape }}` | `s = "<b>"` -> `&lt;b&gt;` (once, not double-escaped)
4. `[{{ missing }}][{{ a.b.c }}][{{ n }}]` | `{"a": {"b": {}}, "n": None}` -> `[][][]`
5. `{{ t|upper }} {{ t|lower }} {{ t|title }}` | `t = "hello woRLD"` -> `HELLO WORLD hello world Hello World`
6. `{{ tags|join:", " }} / {{ tags|length }}` | `{"tags": ["a", "b"]}` -> `a, b / 2`; `{{ tags|join:" | "|safe }}` -> `a | b`
7. `{{ nick|default:"anon" }}` | `{}` -> `anon`; `{"nick": ""}` -> `anon`; `{"nick": 0}` -> `0`
8. `{% for t in tags %}{{ loop.index }}:{{ t }}{% if not loop.last %}, {% endif %}{% endfor %}` | `{"tags": ["a", "b"]}` -> `1:a, 2:b`
9. `{% if n > 1 %}x{% endif %}` -> `TemplateError` (bad `if` expression); `{{ a|bogus }}`, `{{ name`, `{% for x in y %}no end`, `{% endif %}`, `{% if a %}{% else %}{% else %}{% endif %}` -> `TemplateError`
10. `{% if a %}A{% elif b %}B{% else %}C{% endif %}` | `{"a": 0, "b": [1]}` -> `B`; `{"a": 0, "b": []}` -> `C`
11. `{% if x %}\nA\n{% endif %}\n` | `{"x": True}` -> `\nA\n\n`; `{"x": False}` -> `\n`
12. `{% for p in posts %}{{ p.title }}{% endfor %}|{% for p in nothing %}x{% endfor %}` | `{"posts": [{"title": "T1"}, {"title": "T2"}]}` -> `T1T2|`
13. `` (empty template) -> `` ; `{{ items.0 }}-{{ items.5 }}` | `{"items": ["z"]}` -> `z-`

## 5. slug.py

`slugify(text: str) -> str`: (1) Unicode NFKD normalize; (2) encode to ASCII ignoring unencodable chars (accents drop, CJK etc. vanish); (3) lowercase; (4) replace each run of characters outside `[a-z0-9]` with one `-`; (5) strip leading/trailing `-`. May return `""`.

`unique_slug(text: str, taken: set[str]) -> str`: `base = slugify(text) or "untitled"`. If `base not in taken` return it; else return the first of `base-2`, `base-3`, ... not in `taken`. Does **not** mutate `taken`.

Examples: `slugify("Hello, World!")`=`hello-world`; `"  Multiple   Spaces  "`=`multiple-spaces`; `"Café Münster"`=`cafe-munster`; `"C++ & Rust"`=`c-rust`; `"Don't Stop"`=`don-t-stop`; `"snake_case v1.2.3"`=`snake-case-v1-2-3`; `"---"`, `""`, `"日本語"` = `""`. `unique_slug("Hello", set())`=`hello`; `("Hello", {"hello"})`=`hello-2`; `("Hello", {"hello","hello-2"})`=`hello-3`; `("!!!", set())`=`untitled`; `("!!!", {"untitled"})`=`untitled-2`; `("Hello 2", {"hello-2"})`=`hello-2-2`.

## 7. search.py

`STOPWORDS` (module constant, a frozenset): `a an and are as at be by for from in is it of on or that the to with`.

`tokenize(s: str) -> list[str]`: `re.findall(r"[a-z0-9]+", s.lower())`, then drop stopwords. Order and repeats kept. (Non-ASCII letters split words: `café` -> `["caf"]`.) One-letter non-stopword tokens are kept.

`build_index(docs: list[dict]) -> dict`: each doc has `slug`, `title`, `text` (all str). A doc's tokens = `tokenize(title) + tokenize(text)`. Missing keys or a duplicate slug -> `ValueError`. Shape (insertion order sorted: terms alphabetical, slugs alphabetical):
```
{"docs": {SLUG: {"title": TITLE, "length": NUM_TOKENS}}, "terms": {TERM: {SLUG: TF}}}
```
TF = occurrences of TERM in the doc's tokens (only TF >= 1 present).

`search(index: dict, query: str, limit: int = 10) -> list[str]`: terms = distinct `tokenize(query)` tokens. No terms -> `[]`. A doc matches only if it contains **all** terms (AND). Score = sum of TF of the terms in that doc. Sort by score descending, then slug ascending; return the first `limit` slugs (`limit <= 0` -> `[]`). An unknown term -> `[]`.

Example `docs=[{"slug":"b","title":"Beta","text":"the beta and alpha"},{"slug":"a","title":"Alpha","text":"alpha alpha"}]`:
`build_index` -> `{"docs":{"a":{"title":"Alpha","length":3},"b":{"title":"Beta","length":3}},"terms":{"alpha":{"a":3,"b":1},"beta":{"b":2}}}`.
`search(idx,"alpha")` -> `["a","b"]`; `"ALPHA"` with `limit=1` -> `["a"]`; `"alpha beta"` -> `["b"]`; `"alpha alpha"` -> `["a","b"]` (duplicate query terms count once); `"the of"` -> `[]`; `"zzz"` -> `[]`; `""` -> `[]`. Tie: docs `z` and `m` both only `foo`: `search(idx,"foo")` -> `["m","z"]`. `build_index([])` -> `{"docs":{},"terms":{}}`. `tokenize("The Cat & the HAT, x2!")` -> `["cat","hat","x2"]`.

## 11. Out of scope

Nested lists, loose lists, tables, setext headings, reference links, autolinks, raw HTML pass-through, hard line breaks, backslash escapes; YAML maps/multi-line values/block lists/anchors; template inheritance/includes/macros/`set`/comments/whitespace control/comparison operators/`and`/`or`; non-ASCII slug transliteration; pagination; draft previews; watch/serve mode; incremental builds; config files other than `site.toml`; Windows-specific path handling in link resolution; network access; RSS feeds, link checking, site building and the CLI.
