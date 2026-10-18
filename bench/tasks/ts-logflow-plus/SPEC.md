# logflow-plus

`logflow-plus` is a log-processing tool with a plugin registry. It reads application log
text on standard input, parses it into records, normalises them, runs them through a chain
of stages, and prints either the records, a text report or an aggregated table. Stages and
reports are looked up by name in a registry that plugins can extend. Build it from this SPEC
in the (empty) current directory.

## Behaviour (language-neutral)

### Shared contract

A **record** has: `ts` (integer, milliseconds since the Unix epoch, UTC), `level` (one of
`debug`, `info`, `warn`, `error`), `service` (string), `msg` (string) and `fields` (map from
string to string). A **table** has `columns` (list of strings) and `rows` (list of lists of
strings, each as long as `columns`). A **transform** is `(records, args) -> records`; a
**report** is `(records, args) -> text`; a **table report** is `(records, args) -> table`.
`args` is a map from string to string. A **plugin** has a `name` and optional maps from
short names to transforms, reports and table reports. Bad arguments raise a **StageError**
carrying a message; nothing here ever prints, exits or changes its input. Text results are a
sequence of lines, each ending in `\n`, or the empty string. String comparison and sorting
("ascending") is by Unicode code point.

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

### Unit 3 - format

`fmtNumber(x) -> text`: `x` rounded to 6 decimals, trailing zeros and a trailing `.` removed,
never `-0`: `3` -> `3`, `0.1+0.2` -> `0.3`, `-1.25` -> `-1.25`, `0.0000001` -> `0`.

### Unit 4 - aliases

- `SERVICE_ALIASES`: the table `authsvc`->`auth`, `auth-service`->`auth`, `api-gw`->`api`,
  `gateway`->`api`, `database`->`db`, `postgres`->`db`, `pg`->`db`, `cache`->`redis`.
- `canonicalService(name) -> text`: the lower-cased name, mapped through `SERVICE_ALIASES`
  when the lower-cased name is a key.
- `normaliseKey(key) -> text`: the lower-cased key with every `.` replaced by `_`.

### Unit 5 - parse

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

### Unit 6 - normalise (transform)

Arguments `service`, `keys`, `ws`, each `on` (default) or `off`; any other name or value
raises StageError. For every record: with `service` on, `service` becomes
`canonicalService(service)`; with `keys` on, every field key becomes `normaliseKey(key)` (when
two keys collide the later one wins); with `ws` on, every run of whitespace in `msg` becomes one
space and `msg` is trimmed. Everything else is unchanged.

### Unit 7 - filter (transform)

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

### Unit 8 - dedupe (transform)

Arguments: `window` (duration, default `5s`); unknown argument raises StageError. A record
is merged into the earlier kept record with the same `service`, `level` and `msg` when
`0 <= ts - kept.ts <= window` (measured from the kept record, the first of the run);
otherwise it is kept as a new record. Kept records stay in input order. A kept record that
absorbed others gets the field `repeat` set to the total number of occurrences (as text);
records that absorbed nothing are unchanged.

### Unit 9 - redact (transform)

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

### Unit 10 - count (report)

Arguments: `by` (required): `service`, `level`, `minute` (the UTC minute `YYYY-MM-DDTHH:MM`),
or `field:NAME` (records without that field are skipped); `limit` (optional positive
integer). Prints one line `<key> <count>` per distinct key, sorted by count descending then
key ascending, truncated to `limit`. Missing or unknown `by`, bad `limit` or unknown
argument raises StageError. No records prints nothing.

### Unit 11 - percentile (report)

Arguments: `field` (required, name of a numeric field), `p` (comma-separated numbers 0-100,
default `50,90,99`), `by` (optional, only `service`); anything else raises StageError.
Values that are not decimal numbers (`-?digits[.digits]` after trimming) are ignored. The
nearest-rank percentile of the sorted values is the value at rank `max(1, ceil(p*n/100))`.
One line per group (group name `all`, or each service with `by=service`, ascending; groups
with no values are omitted): `<group> n=<n> p<P>=<value> ...` with `P` written as given.
No values at all prints nothing.

### Unit 12 - topmsg (report)

Arguments: `n` (positive integer, default 5), nothing else. Each message is turned into a
template: every `0x` hex number becomes `<hex>`, then every remaining decimal number
(`digits` or `digits.digits`) becomes `<n>`. Prints the `n` most frequent templates as
`<count> <template>` lines, count descending then template ascending.

### Unit 13 - rollup (table report)

Arguments: `by` (required, same forms as `count`: `service`, `level`, `minute`,
`field:NAME`), `fn` (`count` default, `sum`, `avg`, `min`, `max`) and `field` (the numeric
field to aggregate, required unless `fn` is `count`); anything else raises StageError.
Records without the `by` key are skipped. For `count`, each record adds 1. For the other
functions, only records whose `field` holds a decimal number (`-?digits[.digits]` after
trimming) contribute. The table has columns `key`, `value`, `n` (the number of records
that contributed), and one row per key with `n > 0`, ascending by key. `value` is the
count, or the sum/average/minimum/maximum written with `fmtNumber`.

### Unit 14 - render

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

### Unit 15 - renderTable

`renderTable(table, format) -> text`, format `text`, `json` or `csv` (anything else raises
StageError `unknown format: <format>`).
- `text`: the header row, then each row, cells joined by a tab, each row ending in `\n`.
- `json`: one JSON object per row (keys are the columns in order, values the cells), one per
  line; no rows prints nothing.
- `csv`: the header row and the rows, cells joined by `,`; a cell containing `,`, `"` or a
  newline is double-quoted with `"` doubled.

### Unit 16 - registry

A `Registry` holds named transforms ("stage"), reports ("report") and table reports ("table").
A valid name is dot-separated parts, each `[a-z][a-z0-9_]*`. Names are unique across all three kinds.
- `addTransform(name, fn)`, `addReport(name, fn)`, `addTable(name, fn)`: an invalid name raises
  StageError `bad name: <name>`; a name already used raises StageError `duplicate name: <name>`.
- `addPlugin(plugin)`: registers every entry as `<plugin.name>.<key>` (the plugin name must be a
  valid name and each key a single part, else `bad name: <it>`). A duplicate or bad name raises the
  same errors, and then nothing from that plugin is registered.
- `getTransform(name)`, `getReport(name)`, `getTable(name)`: the function, or nothing.
- `list() -> list of text`: `stage <name>` lines, then `report <name>` lines, then `table <name>`
  lines, each group ascending by name.
- `defaultRegistry() -> Registry` (a new one on every call): stages `filter`, `dedupe`, `redact`,
  `normalise`; reports `count`, `percentile`, `topmsg`; table report `rollup`.

### Unit 17 - pipeline (integration)

`runPipeline(input, spec, registry?) -> { code, out, err }` with
`spec = { stages: [text], report?: text, format?: text }`; the registry defaults to
`defaultRegistry()`. A stage or report text is `name` or `name:key=value,key=value` (split the
name at the first `:`, the arguments at `,`, each at its first `=`; a part without `=` or
with an empty key raises StageError `bad argument: <part>`). Order of work: look up every
stage by name (unknown raises StageError `unknown stage <name>`) and the report (a report, else
a table report, else StageError `unknown report <name>`), `parseAll(input)`, apply the
transforms in order, then output: the report text; or the table report's table through
`renderTable(table, format)` (default `text`); or, with no report, `render(records, format)`
(default `text`). `format` is ignored by plain reports.
- Success: code 0, `out` is that output, `err` is `warning: <N> unparseable line(s)\n` when
  `bad` is N > 0, otherwise empty.
- A StageError anywhere: code 2, `out` empty, `err` is `error: <message>\n`.

### Unit 18 - CLI

`logflow [--list] [--stage SPEC]... [--report SPEC] [--format F]` (value options also as
`--opt=VALUE`). `--list` prints `defaultRegistry().list()`, one entry per line, exits 0 and
reads no input. Otherwise it reads standard input as UTF-8, calls `runPipeline`, writes `out`
and `err` and exits with the code. An unknown option or a missing option value: code 2, one
`usage:` line on standard error, nothing on standard output. A 5 MB input must finish in a few
seconds.

### Input example

```
2024-03-05T10:15:30Z [WARN] AuthSvc: login failed user=bob ip=10.1.2.3
2024-03-05T10:15:31.250Z [info] api: GET /items took 42ms status=200 latency_ms=42
```

## TypeScript layout (this implementation)

- `package.json`: `"type": "module"`, scripts `"build": "tsc"` and `"test": "vitest run"`, dev
  dependencies `typescript`, `vitest`, `@types/node`. `tsconfig.json`: strict, ES2022, module
  NodeNext, `rootDir` `src`, `outDir` `dist`, only `src` compiled. Imports use the `.js` suffix.
- `src/types.ts`: `Level`, `Rec` (the record), `Table`, `StageError` (class extending `Error`),
  `Args`, `Transform`, `Report`, `TableReport`, `Plugin` as defined above.
- `src/levels.ts` (`LEVELS`, `normalizeLevel`, `levelRank`), `src/duration.ts`
  (`parseDuration`, `formatDuration`), `src/format.ts` (`fmtNumber`), `src/aliases.ts`
  (`SERVICE_ALIASES`, `canonicalService`, `normaliseKey`), `src/parse.ts` (`parseLine`, `parseAll`).
- `src/stages/{filter,dedupe,redact,normalise}.ts` (named exports `filter`, `dedupe`, `redact`,
  `normalise`); `src/reports/{count,percentile,topmsg,rollup}.ts` (`count`, `percentile`,
  `topmsg`, and `rollup` returning a table).
- `src/render.ts` (`render`), `src/render-table.ts` (`renderTable`), `src/registry.ts`
  (`Registry`, `defaultRegistry`), `src/pipeline.ts` (`runPipeline`, `PipelineSpec`),
  `src/cli.ts` (entry, run as `node dist/cli.js ...` after `npm run build`).
- `tests/*.test.ts`: your own vitest tests, at least one file per unit above.
- Done when `npm install`, `npm run build` and `npm test` succeed and the work is committed.

## Units

1. levels, 2. duration, 3. format, 4. aliases, 5. parse, 6. normalise, 7. filter, 8. dedupe,
9. redact, 10. count, 11. percentile, 12. topmsg, 13. rollup, 14. render, 15. renderTable,
16. registry, 17. pipeline, 18. CLI. Units 1 to 4 need only the shared contract; units 5 to 16
need only the shared contract plus units 1 to 4 (the registry also needs the stage and report
units 6 to 13 for `defaultRegistry`); 17 needs 5, 14, 15 and 16; 18 needs 16 and 17.
The data flows parse -> normalise -> stages -> rollup -> renderTable.
