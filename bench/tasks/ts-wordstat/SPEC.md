# wordstat

`wordstat` is a small command-line tool: it reads text on standard input and prints the
most frequent words. Build it from this SPEC in the (empty) current directory.

## Behaviour (language-neutral)

### Module 1 - tokenize

`tokenize(text: string) -> list of string`

- Lowercases the text, then returns the maximal runs of letters, in order of appearance.
- A letter is any Unicode letter (general category L*), so `é`, `ß`, `ж`, `日` are letters.
- Every other character (digits, whitespace, punctuation, symbols, apostrophes, hyphens)
  is a separator. `"don't"` gives `["don", "t"]`; `"a1b"` gives `["a", "b"]`.
- No empty tokens are ever returned. `""` or text without letters gives `[]`.
- Lowercasing is Unicode-aware: `"ÉCOLE"` gives `["école"]`.

### Module 2 - countWords

`countWords(tokens: list of string) -> map from string to integer`

- The number of occurrences of each distinct token. Empty input gives an empty map.
- The input is not modified.

### Module 3 - topN

`topN(counts: map from string to integer, n: integer) -> list of (string, integer)`

- Returns the `n` entries with the highest counts, ordered by count descending, then by
  word ascending (plain code-point order, `"a" < "b" < "é"`).
- If there are fewer than `n` entries, returns all of them. `n <= 0` returns an empty list.
- The input is not modified.

### Module 4 - CLI

`wordstat [--top N]`

- Reads all of standard input (UTF-8), tokenizes, counts, takes `topN(counts, N)`.
- `--top N` (also accepted as `--top=N`): `N` must be a positive integer. Default `10`.
- Prints one line per result to standard output: the word, one space, the count, then
  a newline (`"the 12\n"`). No header, no trailing blank line.
- Empty input, or input without letters, prints nothing and exits `0`.
- Exit codes: `0` success; `2` usage error (unknown argument, `--top` missing its value,
  or `N` not a positive integer such as `0`, `-3`, `abc`, `2.5`). On a usage error,
  print one line starting with `usage:` to standard error and nothing to standard output.
- Must handle a 5 MB input in a few seconds.

## TypeScript layout (this implementation)

- `package.json`: `"type": "module"`, scripts `"build": "tsc"` and `"test": "vitest run"`,
  dev dependencies `typescript`, `vitest`, `@types/node`.
- `tsconfig.json`: strict, ES2022, module NodeNext, `rootDir` `src`, `outDir` `dist`,
  and only `src` compiled (tests are not part of the build).
- `src/tokenize.ts` exports `tokenize`; `src/count.ts` exports `countWords`
  (returns a `Map<string, number>`); `src/topn.ts` exports `topN`
  (takes a `Map<string, number>`, returns `[string, number][]`); `src/cli.ts` is the entry.
- The CLI is run as `node dist/cli.js --top N` after `npm run build`.
- Relative imports use the `.js` suffix (NodeNext), e.g. `import { tokenize } from "./tokenize.js"`.
- `tests/`: your own vitest tests (`tests/*.test.ts`).
- Done when `npm install`, `npm run build` and `npm test` succeed and the work is committed.

## Tasks

1. tokenize, 2. countWords and topN, 3. CLI, 4. tests and project setup.
