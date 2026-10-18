import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import { main } from "../src/cli.js";
import { capture, makeTempDir, siteFactory, writeFiles } from "./helpers.js";

describe("cli", () => {
  test("build success prints summary line", () => {
    const { src, out } = siteFactory();
    const c = capture();
    const code = main(["build", src, out], c.io);
    expect(code).toBe(0);
    expect(c.stdout()).toBe("built: 2 posts, 2 tag pages, 1 static files, 1 drafts skipped\n");
    expect(fs.statSync(path.join(out, "index.html")).isFile()).toBe(true);
  });

  test("build failure prints error to stderr and returns 1", () => {
    const { src, out } = siteFactory({ "site.json": null });
    const c = capture();
    const code = main(["build", src, out], c.io);
    expect(code).toBe(1);
    expect(c.stderr().startsWith("error: ")).toBe(true);
    expect(c.stdout()).toBe("");
  });

  test("check: not a directory", () => {
    const missing = path.join(makeTempDir(), "nope");
    const c = capture();
    const code = main(["check", missing], c.io);
    expect(code).toBe(1);
    expect(c.stderr().split("\n")).toContain(`error: not a directory: ${missing}`);
  });

  test("check reports broken links and exit 1", () => {
    const d = makeTempDir();
    writeFiles(d, {
      "index.html": '<a href="/missing">m</a><a href="/about.html">a</a>',
      "about.html": "",
      "feed.xml": "<a href='/zzz'>",
    });
    const c = capture();
    const code = main(["check", d], c.io);
    expect(code).toBe(1);
    expect(c.stdout().split("\n").filter((l) => l !== "")).toEqual([
      "broken: /index.html -> /missing",
      "checked 2 pages, 1 broken links",
    ]);
  });

  test("usage errors return 2 without throwing", () => {
    const d = makeTempDir();
    const c = capture();
    expect(main([], c.io)).toBe(2);
    expect(main(["frobnicate"], c.io)).toBe(2);
    expect(main(["build", "only-one"], c.io)).toBe(2);
    expect(main(["check", d, "extra"], c.io)).toBe(2);
    expect(main(["check", "--bogus", d], c.io)).toBe(2);
  });
});
