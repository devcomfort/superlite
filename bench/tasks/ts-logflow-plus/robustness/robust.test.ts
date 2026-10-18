import { expect, test } from "vitest";
import { cli } from "./helpers.js";
import { defaultRegistry } from "../src/registry.js";

test("huge input (~5 MB) through report pipelines", () => {
  const services = ["api", "auth", "db", "web"];
  const lines: string[] = [];
  let size = 0;
  let i = 0;
  const per: Record<string, number> = {};
  while (size < 5 * 1024 * 1024) {
    const svc = services[i % 4];
    const sec = String(i % 60).padStart(2, "0");
    const line = `2024-03-05T10:00:${sec}Z [info] ${svc}: request ${i} handled in ${i % 50}ms latency_ms=${i % 50} user=u${i % 7}`;
    lines.push(line);
    per[svc] = (per[svc] ?? 0) + 1;
    size += line.length + 1;
    i++;
  }
  const text = lines.join("\n") + "\n";
  const t0 = Date.now();
  const counted = cli(text, "--report", "count:by=service");
  expect(counted.code).toBe(0);
  expect(counted.out).toBe(Object.entries(per).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([k, n]) => `${k} ${n}\n`).join(""));
  const pct = cli(text, "--stage", "filter:service=api*", "--report", "percentile:field=latency_ms,p=50");
  expect(pct.code).toBe(0);
  const vals: number[] = [];
  for (let k = 0; k < i; k += 4) vals.push(k % 50);
  vals.sort((x, y) => x - y);
  expect(pct.out).toBe(`all n=${per.api} p50=${vals[Math.max(1, Math.ceil((50 * vals.length) / 100)) - 1]}\n`);
  expect(cli(text, "--stage", "dedupe:window=1h", "--report", "topmsg:n=1").out).toBe(`${i} request <n> handled in <n>ms\n`);
  expect(Date.now() - t0).toBeLessThan(60000);
});

test("one enormous line does not blow up", () => {
  const big = "word ".repeat(250_000);
  const line = `2024-03-05T10:00:00Z [info] api: ${big}k=v`;
  const t0 = Date.now();
  const r = cli(line + "\n2024-03-05T10:00:01Z [info] api: after\n", "--report", "count:by=field:k");
  expect(r.code).toBe(0);
  expect(r.out).toBe("v 1\n");
  const many = cli(`2024-03-05T10:00:00Z [info] api: ${"a=b ".repeat(100_000)}\n`, "--format", "json");
  expect(JSON.parse(many.out).fields).toEqual({ a: "b" });
  expect(Date.now() - t0).toBeLessThan(30000);
});

test("unicode end to end", () => {
  const log = [
    "2024-03-05T10:00:00Z [info] api: héllo wörld 日本語 😀 user=\"zoë ñ\"",
    "2024-03-05T10:00:01Z [warn] api: héllo wörld 日本語 😀 user=\"zoë ñ\"",
  ].join("\n");
  const r = cli(log, "--stage", "filter:grep=日本語", "--format", "json");
  expect(r.code).toBe(0);
  const first = JSON.parse(r.out.split("\n")[0]);
  expect(first.msg).toBe("héllo wörld 日本語 😀");
  expect(first.fields.user).toBe("zoë ñ");
  expect(cli(log, "--report", "count:by=field:user").out).toBe("zoë ñ 2\n");
  expect(cli(log, "--stage", "filter:level=warn", "--format", "csv").out).toContain(",warn,api,héllo wörld 日本語 😀,user=zoë ñ\n");
});

test("empty, blank, binary and CRLF input", () => {
  expect(cli("")).toMatchObject({ code: 0, out: "", err: "" });
  expect(cli("\n\n  \n")).toMatchObject({ code: 0, out: "", err: "" });
  const junk = cli("\u0000\u0001\u0002 garbage\n��\n2024-03-05T10:00:00Z [info] a: ok\r\n");
  expect(junk.code).toBe(0);
  expect(junk.out).toBe("2024-03-05T10:00:00.000Z [INFO] a: ok\n");
  expect(junk.err).toBe("warning: 2 unparseable line(s)\n");
});

test("rollup over a large input and a registry with many plugins", () => {
  const lines: string[] = [];
  for (let i = 0; i < 60_000; i++) {
    const sec = String(i % 60).padStart(2, "0");
    lines.push(`2024-03-05T10:${String(i % 3).padStart(2, "0")}:${sec}Z [info] ${i % 2 ? "AuthSvc" : "api-gw"}: hit latency_ms=${i % 10}`);
  }
  const r = cli(lines.join("\n") + "\n", "--stage", "normalise", "--report", "rollup:by=service,fn=sum,field=latency_ms", "--format", "json");
  expect(r.code).toBe(0);
  const rows = r.out.trim().split("\n").map((l) => JSON.parse(l));
  expect(rows).toEqual([
    { key: "api", value: String(30_000 * 4), n: "30000" },
    { key: "auth", value: String(30_000 * 5), n: "30000" },
  ]);
  const reg = defaultRegistry();
  const t0 = Date.now();
  for (let p = 0; p < 20_000; p++) reg.addPlugin({ name: `p${p}`, transforms: { a: ((x: unknown) => x) as never }, reports: { b: (() => "") as never } });
  expect(reg.list()).toHaveLength(8 + 40_000);
  expect(reg.getTransform("p19999.a")).toBeTypeOf("function");
  expect(Date.now() - t0).toBeLessThan(15000);
});
