const test = require("node:test"),
  assert = require("node:assert/strict"),
  fs = require("node:fs"),
  path = require("node:path");
test("portable manifests preserve Sets, Maps, dates and native target identity", async () => {
  const code = fs.readFileSync(
    path.join(__dirname, "../web/static/portable.js"),
    "utf8",
  );
  const { encodePortable, decodePortable } = await import(
    "data:text/javascript;base64," + Buffer.from(code).toString("base64")
  );
  const original = {
    confirmed: new Set([1, 2]),
    objects: new Map([
      [
        "shape",
        { part: "ppt/slides/slide2.xml", path: "/0/3", fingerprint: "abc" },
      ],
    ]),
    date: new Date("2026-10-20T12:00:00Z"),
    bytes: new Uint8Array([1, 2]),
  };
  assert.deepEqual(
    decodePortable(JSON.parse(JSON.stringify(encodePortable(original)))),
    original,
  );
});
