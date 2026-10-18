import { expect, test } from "vitest";
import { cli } from "./helpers.js";

test("huge input (~5 MB) through every command", () => {
  const chunk = "alpha beta gamma delta alpha\n";
  const n = Math.ceil((5 * 1024 * 1024) / chunk.length);
  const text = chunk.repeat(n);
  const t0 = Date.now();
  expect(cli(text, "wordstat", "--top", "2").out).toBe(`alpha ${2 * n}\nbeta ${n}\n`);
  expect(cli(text, "linestat").out).toBe(`lines ${n}\nwords ${5 * n}\nchars ${chunk.length * n}\nlongest ${chunk.length - 1}\n`);
  const slugs = cli(text, "slugify").out;
  expect(slugs.length).toBe(n * "alpha-beta-gamma-delta-alpha\n".length);
  const csv = "v\n" + "1\n".repeat(1_000_000);
  expect(cli(csv, "csvsum", "--col", "v").out).toBe("1000000\n");
  expect(Date.now() - t0).toBeLessThan(40000);
});

test("unicode end to end", () => {
  expect(cli("Éé éÉ ÉCOLE école\n", "wordstat").out).toBe("école 2\néé 2\n");
  expect(cli("😀 ñandú\n", "linestat").out).toBe("lines 1\nwords 2\nchars 8\nlongest 7\n");
  expect(cli("Ñandú Ж!\n", "slugify").out).toBe("ñandú-ж\n");
});

test("empty input", () => {
  expect(cli("", "wordstat")).toMatchObject({ code: 0, out: "" });
  expect(cli("", "slugify")).toMatchObject({ code: 0, out: "" });
  expect(cli("", "linestat").out).toBe("lines 0\nwords 0\nchars 0\nlongest 0\n");
  expect(cli("", "csvsum", "--col", "a")).toMatchObject({ code: 3, out: "" });
});
