# logflow

`logflow` is a log-processing tool. It reads application log text on standard input, parses
it into records, runs them through a chain of stages, and prints either the records or a
report. Build it from this SPEC in the (empty) current directory.

## Behaviour (language-neutral)

### Shared contract

A **record** has: `ts` (integer, milliseconds since the Unix epoch, UTC), `level` (one of
`debug`, `info`, `warn`, `error`), `service` (string), `msg` (string) and `fields` (map from
string to string). A **transform** is `(records, args) -> records`; a **report** is
`(records, args) -> text`. `args` is a map from string to string. Bad arguments raise a
**StageError** carrying a message; no stage or report ever prints, exits or changes its
input. Text results are a sequence of lines, each ending in `\n`, or the empty string.
Numbers are printed as plain decimals, integers without a fraction (`3`, `0.5`).
String comparison and sorting ("ascending") is by Unicode code point.

### Unit 1 - levels

- `LEVELS`: the four levels in order `debug, info, warn, error`.
- `normalizeLevel(name) -> level or null`: case-insensitive; aliases `trace`->debug,
  `notice`->info, `warning`->warn, `err`->error, `fatal`->error, `critical`->error;
  anything else is null.
- `levelRank(level) -> integer`: debug 10, info 20, warn 30, error 40.

### Unit 2 - duration

- `parseDuration(text) -> integer ms`: one or more `<digits><unit>` parts with no spaces,
  units `d` (86400000), `h` (3600000), `m` (60000), `s` (1000), `ms` (1); parts add up
  (`1h30m` is 5400000, `250ms` is 250, `0s` is 0). Anything else (empty, `5`, `5x`, `1.5h`,
  `-1m`, `m5`) raises StageError `bad duration: <text>`.
- `formatDuration(ms) -> text`: the inverse: non-zero parts, largest unit first, no spaces
  (`5400000` -> `1h30m`, `1500` -> `1s500ms`), and `0` -> `0s`.

### Unit 3 - parse

- `parseLine(line) -> record or null`. A line is
  `<ts> [<LEVEL>] <service>: <rest>` with single spaces as shown. `ts` is UTC ISO-8601
  `YYYY-MM-DDTHH:MM:SS`, optional `.` and 1-9 fraction digits (truncated to milliseconds),
  then `Z`; impossible dates or times (month 13, February 30, second 60) are null. `LEVEL`
  is any case and goes through `normalizeLevel`; unknown is null. `service` matches
  `[A-Za-z0-9_.-]+`. After `service:` comes either end of line or one space and the rest.
  A trailing `\r` on the line is ignored.
- The rest is split into tokens. A **field token** is `key=value`: key `[A-Za-z_][A-Za-z0-9_.]*`,
  value either a bare run of non-space characters (possibly empty) or a double-quoted string
  where `\"` and `\\` are escapes. The **message** is the rest before the first field token,
  trimmed. If every token from the first field token to the end is a field token, those are
  the fields (a repeated key keeps its last value). Otherwise there are no fields and the
  message is the whole rest, trimmed. A rest without field tokens is all message.
- `parseAll(text) -> { records, bad }`: parses every line of `text` (split on `\n`). Blank
  lines are skipped without counting; each non-blank line that does not parse adds 1 to `bad`.

### Unit 4 - filter (transform)

Arguments (all optional, all must hold, input order kept); an unknown argument name raises
StageError `filter: unknown argument <name>`:
- `level`: keep records whose level rank is at least that of the level (via `normalizeLevel`;
  unknown raises StageError).
- `service`: comma-separated patterns, `*` matches any run of characters (including none),
  the whole service must match one pattern.
- `since` and `until`: either `@<epoch ms>` or a duration (via `parseDuration`) meaning that
  long before the latest `ts` in the input. `since` keeps `ts >= bound`, `until` keeps `ts < bound`.
- `grep`: keep records whose `msg` contains the text (case-sensitive substring).
- `field`: `key=value`; keep records whose `fields[key]` equals `value`. A value without
  `=` or with an empty key raises StageError.

### Unit 5 - dedupe (transform)

Arguments: `window` (duration, default `5s`); unknown argument raises StageError. A record
is merged into the earlier kept record with the same `service`, `level` and `msg` when
`0 <= ts - kept.ts <= window` (measured from the kept record, the first of the run);
otherwise it is kept as a new record. Kept records stay in input order. A kept record that
absorbed others gets the field `repeat` set to the total number of occurrences (as text);
records that absorbed nothing are unchanged.

### Unit 6 - redact (transform)

Arguments: `rules` (comma-separated subset of `email`, `ip`, `secret`; default all three) and
`mask` (default `***`); unknown argument or rule raises StageError. Redaction applies to
`msg` and to every field value (not to keys or `service`):
- `email`: an address like `bob@example.com` becomes the mask.
- `ip`: an IPv4 dotted quad (each part 0-255, not touching other digits or dots on the left,
  not followed by a digit) becomes `<first part>.*.*.*`.
- `secret`: a field whose key (any case) is one of `password`, `passwd`, `secret`, `token`,
  `api_key`, `apikey`, `authorization` has its whole value replaced by the mask; in `msg`,
  `password=...`, `passwd=`, `secret=`, `token=`, `api_key=`, `apikey=` (any case, value
  up to the next space) keep the key and get the mask as value.

### Unit 7 - count (report)

Arguments: `by` (required): `service`, `level`, `minute` (the UTC minute `YYYY-MM-DDTHH:MM`),
or `field:NAME` (records without that field are skipped); `limit` (optional positive
integer). Prints one line `<key> <count>` per distinct key, sorted by count descending then
key ascending, truncated to `limit`. Missing or unknown `by`, bad `limit` or unknown
argument raises StageError. No records prints nothing.

### Unit 8 - percentile (report)

Arguments: `field` (required, name of a numeric field), `p` (comma-separated numbers 0-100,
default `50,90,99`), `by` (optional, only `service`); anything else raises StageError.
Values that are not decimal numbers (`-?digits[.digits]` after trimming) are ignored. The
nearest-rank percentile of the sorted values is the value at rank `max(1, ceil(p*n/100))`.
One line per group (group name `all`, or each service with `by=service`, ascending; groups
with no values are omitted): `<group> n=<n> p<P>=<value> ...` with `P` written as given.
No values at all prints nothing.

### Unit 9 - topmsg (report)

Arguments: `n` (positive integer, default 5), nothing else. Each message is turned into a
template: every `0x` hex number becomes `<hex>`, then every remaining decimal number
(`digits` or `digits.digits`) becomes `<n>`. Prints the `n` most frequent templates as
`<count> <template>` lines, count descending then template ascending.

### Unit 10 - render

`render(records, format) -> text`, format `text`, `json` or `csv` (anything else raises
StageError `unknown format: <format>`). Timestamps are `YYYY-MM-DDTHH:MM:SS.mmmZ` (UTC).
Fields are ordered by key ascending.
- `text`: `<ts> [<LEVEL>] <service>: <msg> key=value ...` one line per record (level in upper
  case; the space before an empty message is omitted). A value that is empty or contains
  whitespace, `"`, `=` or `\` is written in double quotes with `\` and `"` escaped.
- `json`: one JSON object per line with keys in this order: `ts` (the ISO text), `level`,
  `service`, `msg`, `fields` (object, keys ascending).
- `csv`: header `ts,level,service,msg,fields`, then one row per record; `fields` is
  `key=value` pairs joined by `;`. A cell containing `,`, `"` or a newline is double-quoted
  with `"` doubled. Rows end in `\n`; no records still prints the header.

### Unit 11 - pipeline (integration)

`runPipeline(input, spec) -> { code, out, err }` with `spec = { stages: [text], report?: text,
format?: text }`. A stage or report text is `name` or `name:key=value,key=value` (split the
name at the first `:`, the arguments at `,`, each at its first `=`; a part without `=` or
with an empty key raises StageError `bad argument: <part>`). Transforms: `filter`, `dedupe`,
`redact`; reports: `count`, `percentile`, `topmsg`. Order of work: check every stage and the
report name (unknown name raises StageError `unknown stage <name>` or `unknown report
<name>`), `parseAll(input)`, apply the transforms in order, then output the report text if
there is a report, otherwise `render(records, format)` (default `text`).
- Success: code 0, `out` is that output, `err` is `warning: <N> unparseable line(s)\n` when
  `bad` is N > 0, otherwise empty.
- A StageError anywhere: code 2, `out` empty, `err` is `error: <message>\n`.

### Unit 12 - CLI

`logflow [--stage SPEC]... [--report SPEC] [--format F]` (each option also as `--opt=VALUE`).
It reads standard input as UTF-8, calls `runPipeline`, writes `out` and `err` and exits with
the code. An unknown option or a missing option value: code 2, one `usage:` line on standard
error, nothing on standard output. A 5 MB input must finish in a few seconds.

### Input example

```
2024-03-05T10:15:30Z [WARN] auth: login failed user=bob ip=10.1.2.3
2024-03-05T10:15:31.250Z [info] api: GET /items took 42ms status=200 latency_ms=42
```

## TypeScript layout (this implementation)

- `package.json`: `"type": "module"`, scripts `"build": "tsc"` and `"test": "vitest run"`, dev
  dependencies `typescript`, `vitest`, `@types/node`. `tsconfig.json`: strict, ES2022, module
  NodeNext, `rootDir` `src`, `outDir` `dist`, only `src` compiled. Imports use the `.js` suffix.
- `src/types.ts`: `Level`, `Rec` (the record), `StageError` (class extending `Error`), `Args`,
  `Transform`, `Report` as defined above.
- `src/levels.ts` (`LEVELS`, `normalizeLevel`, `levelRank`), `src/duration.ts`
  (`parseDuration`, `formatDuration`), `src/parse.ts` (`parseLine`, `parseAll`).
- `src/stages/filter.ts` (`filter`), `src/stages/dedupe.ts` (`dedupe`),
  `src/stages/redact.ts` (`redact`); `src/reports/count.ts` (`count`),
  `src/reports/percentile.ts` (`percentile`), `src/reports/topmsg.ts` (`topmsg`);
  each is a named export with the transform or report signature.
- `src/render.ts` (`render`), `src/pipeline.ts` (`runPipeline`, `PipelineSpec`),
  `src/cli.ts` (entry, run as `node dist/cli.js ...` after `npm run build`).
- `tests/*.test.ts`: your own vitest tests, at least one file per unit above.
- Done when `npm install`, `npm run build` and `npm test` succeed and the work is committed.

## Units

1. levels, 2. duration, 3. parse, 4. filter, 5. dedupe, 6. redact, 7. count, 8. percentile,
9. topmsg, 10. render, 11. pipeline, 12. CLI. Units 1 and 2 need only the shared contract; units
3 to 10 need only the shared contract plus units 1 and 2; 11 needs 3 to 10; 12 needs 11.
