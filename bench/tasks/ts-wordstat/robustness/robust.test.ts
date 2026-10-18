import { expect, test } from "vitest";
import { cli } from "./helpers.js";

test("huge input (~5 MB) finishes and counts correctly", () => {
  const words = ["alpha", "beta", "gamma", "delta"];
  const chunk = words.join(" ") + " alpha\n";
  const text = chunk.repeat(Math.ceil((5 * 1024 * 1024) / chunk.length));
  const n = Math.ceil((5 * 1024 * 1024) / chunk.length);
  const t0 = Date.now();
  const r = cli(text, "--top", "2");
  expect(r.code).toBe(0);
  expect(r.out).toBe(`alpha ${2 * n}\nbeta ${n}\n`);
  expect(Date.now() - t0).toBeLessThan(15000);
});

test("unicode end to end", () => {
  const r = cli("Éé éÉ ÉCOLE école ñandú Ñandú\n", "--top", "3");
  expect(r.code).toBe(0);
  expect(r.out).toBe("école 2\néé 2\nñandú 2\n");
});

test("whitespace-only and symbol-only input is empty output", () => {
  for (const s of ["", "   \n\t\n", "123 !!! ---"]) {
    const r = cli(s);
    expect(r.code).toBe(0);
    expect(r.out).toBe("");
  }
});
