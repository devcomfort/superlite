# textkit

`textkit` is a small command-line toolbox: `textkit <command> [options]` reads text on
standard input and prints a result. Four independent commands share one calling contract
and one dispatcher. Build it from this SPEC in the (empty) current directory.

## Behaviour (language-neutral)

### Command contract

Every command is a function `run(args, input) -> (code, out, err)`:
`args` is the list of its own arguments (without the command name), `input` is all of
standard input as text, and the result is an exit code, the text for standard output and
the text for standard error. A command never prints or exits by itself. Exit codes:
`0` success, `2` usage error, `3` data error. On any non-zero code, `out` is empty and
`err` is one line ending in a newline; a usage error line starts with `usage:`, a data
error line starts with `error:`.

### Command 1 - wordstat

`wordstat [--top N]` (also `--top=N`). `N` must be a positive integer, default `10`,
otherwise code 2 (unknown argument, missing value, `0`, `-3`, `abc`, `2.5`).

- Tokens: lowercase the input, then take the maximal runs of Unicode letters; every other
  character (digits, whitespace, punctuation) separates tokens.
- Counts each distinct token and prints the `N` most frequent, ordered by count
  descending, then word ascending (code-point order), one line `word count` each.
- Fewer than `N` distinct words prints all of them. No letters at all prints nothing, code 0.

### Command 2 - linestat

`linestat` takes no arguments (any argument is code 2). It prints exactly four lines:
`lines L`, `words W`, `chars C`, `longest M`.

- `lines`: the number of `\n`-terminated lines, plus one if text remains after the last
  `\n`. Empty input has 0 lines.
- `words`: the number of maximal runs of non-whitespace characters.
- `chars`: the number of Unicode code points in the whole input, newlines included.
- `longest`: the most code points in one line, not counting its `\n` (0 for empty input).

Example: input `"ab cd\nefg\n"` prints `lines 2`, `words 3`, `chars 10`, `longest 5`.

### Command 3 - csvsum

`csvsum --col NAME` (also `--col=NAME`) sums one numeric column of simple CSV. `--col` is
required, otherwise code 2.

- The first non-blank line is the header: names separated by `,`. Cells are trimmed. There
  is no quoting. Blank lines are skipped and a trailing `\r` on a line is ignored.
- Sums the column `NAME` over all data rows. An empty cell is skipped. Any other cell must
  be a decimal number (optional leading `-`, digits, optional `.digits`), otherwise code 3
  with `error: row R: not a number`, where `R` is the 1-based data row number.
- Unknown column, or input without a header: code 3 (`error: no such column`, or
  `error: no header`). A row too short to reach the column counts as an empty cell.
- Prints the sum rounded to 6 decimals with trailing zeros and a trailing `.` removed
  (`3`, `0.3`, `-1.25`), then a newline. Header only prints `0`.

### Command 4 - slugify

`slugify` takes no arguments (any argument is code 2). Each input line becomes one output
line: lowercase it, turn every maximal run of non-letter, non-digit characters (Unicode
letters and digits are kept) into one `-`, then strip leading and trailing `-`.

- `"Hello, World!"` gives `hello-world`; `"  --A  b-- "` gives `a-b`;
  `"Ünï cödé 42"` gives `ünï-cödé-42`; a line with no letters or digits gives an empty line.
- A final `\n` does not add a line; empty input prints nothing. Output lines end in `\n`.

### Dispatcher

`textkit <command> [args...]` selects the command by its first argument, reads standard
input as UTF-8, calls `run`, writes `out` to standard output and `err` to standard error
and exits with the code. No command or an unknown command: code 2, one `usage:` line on
standard error listing the four commands. `--help` as the first argument prints the same
line to standard output and exits 0. A 5 MB input to any command must finish in a few seconds.

## TypeScript layout (this implementation)

- `package.json`: `"type": "module"`, scripts `"build": "tsc"` and `"test": "vitest run"`,
  dev dependencies `typescript`, `vitest`, `@types/node`.
- `tsconfig.json`: strict, ES2022, module NodeNext, `rootDir` `src`, `outDir` `dist`,
  only `src` compiled (tests are not part of the build).
- `src/commands/wordstat.ts`, `linestat.ts`, `csvsum.ts`, `slugify.ts`: each exports
  `run(args: string[], input: string): { code: number; out: string; err: string }`.
- `src/cli.ts` is the dispatcher, run as `node dist/cli.js <command> ...` after `npm run build`.
- Relative imports use the `.js` suffix (NodeNext).
- `tests/*.test.ts`: your own vitest tests, at least one file per command plus the dispatcher.
- Done when `npm install`, `npm run build` and `npm test` succeed and the work is committed.

## Tasks

1. wordstat. 2. linestat. 3. csvsum. 4. slugify. 5. dispatcher and `cli.ts`.
6. project setup, per-command tests and the dispatcher test.
Tasks 1-4 are independent of each other; 5 needs the contract above; 6 needs all.
