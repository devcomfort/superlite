## Stop 1 (decider 13s)

### Agent asked

I've written the combined design and plan to `docs/plans/2026-10-17-sitegen.md` and need your approval before I write any code.

**How it's built:**
- **Separate modules.** Seven self-contained modules: front matter, markdown, templates, slug/feed/search and links. They don't depend on each other, so they get built in parallel.
- **Two modules tie it together.** `site.py` runs the build and `cli.py` provides the command line. They're built last.
- **Tests.** Each module has its own pytest file covering every example in SPEC.md, plus the error cases the spec implies.

**Decisions I made where the spec leaves room** (they're recorded in the doc):
1. If a post's `slug` or `summary` isn't a string, or its `tags` isn't a list of strings, the build fails with a `BuildError`.
2. A post's `title` is checked for being non-empty with surrounding spaces ignored, but it's stored and shown exactly as written.
3. I treat SPEC.md as the binding contract. The plan points to its sections rather than copying them.

**Question:** Do you approve the plan as written, or do you want to change any of the three decisions above?

### Decider answered

Approved. Build the modules in parallel as you proposed.

1. Keep it. A `slug` or `summary` that isn't a string, or `tags` that isn't a list of strings, raises `BuildError`. An empty `slug` counts as absent.
2. Keep it. Check that `title` is non-empty after stripping, but store and render it exactly as written.
3. Keep it. SPEC.md is the binding contract.

Also make sure the plan covers these, which your summary doesn't mention:
- §0 project setup: `pyproject.toml` with a `[build-system]` and a dev group containing `pytest`, and `uv run pytest` working.
- `errors.py`, with its exception hierarchy.
- `__main__.py`.

The modules share `errors.py` and `esc`.

## Stop 2 (decider 17s)

### Agent asked

`sitegen` is built and committed on the branch `superlite/sitegen`: 9 commits ahead of `main`, nothing uncommitted, and no remote exists. `uv run pytest` gives 190 passed. `python -m sitegen --help` exits 0, and running it with no command exits 2 as the spec requires.

**What's in it:** all eleven modules from SPEC.md, each with its own tests. The project setup is in place: `pyproject.toml` with a build system and a dev group containing `pytest`, plus `errors.py` with the exception hierarchy and `__main__.py`. The modules share one escape function, defined in `src/sitegen/__init__.py`. I also added a `.gitattributes` file that keeps line endings as plain LF on Windows, so test strings don't get altered at checkout.

**Reviews:** both the review of the first five modules and the final review of the whole branch approved the work with no serious findings. I fixed the two small issues they raised: a front-matter integer longer than Python's 4,300-digit limit now raises `FrontmatterError`, and I replaced a test check that could never fail.

**Decisions I made** (the three you confirmed aren't repeated):
1. A list item in front matter that contains `[` anywhere, such as `[a[b]`, is rejected. If the spec meant only a whole nested list, items like that will fail.
2. In templates, `{{ x|escape }}` outputs nothing when `x` is missing or `None`, the same as plain output. A literal reading of the spec would give `None`.
3. A bare `tags:` with no value fails the build, because the spec only lets `slug` treat an empty value as absent. If an empty `tags:` should mean no tags, those posts will currently fail to build.
4. `{% if not %}` is read as a lookup of a variable named `not` rather than an error.
5. Markdown removes NUL (`\x00`) characters from its input so they can't collide with internal markers. The spec doesn't mention this.

**Question:** what should happen to the branch?
1. Merge it locally into `main` (my recommendation).
2. Keep it on `superlite/sitegen` as it is.

Pushing or opening a pull request is off the table, since you said not to push.

### Decider answered

Merge it locally into `main`. Don't push.

Before you merge, change two of your decisions:
- **#2:** Follow the SPEC literally. `escape` is `esc(str(value))`, so `None` gives `None`. Undefined can still give `""`.
- **#5:** Don't remove NUL characters. The SPEC says to escape everything, not drop input. Use a placeholder scheme that can't collide with input text and keeps NULs in the output.

Keep the other three:
- **#1:** Keep it. The SPEC rejects a nested `[`, and your reading is acceptable.
- **#3:** Keep it. A bare `tags:` parses as `""`, which is not a list, so `BuildError` is correct.
- **#4:** Keep it. `not` has to be followed by whitespace, so a bare `not` is a path.

