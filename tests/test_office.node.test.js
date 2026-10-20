const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");
const root = path.join(__dirname, ".."),
  base = process.env.WORKSHOP_TEST_URL || "http://127.0.0.1:8188";
let server;
test.before(async () => {
  if (process.env.WORKSHOP_TEST_URL) return;
  server = spawn(
    path.join(root, ".venv/bin/python"),
    ["-m", "flask", "--app", "web.app", "run", "--port", "8188"],
    {
      cwd: root,
      env: { ...process.env, FLASK_SKIP_DOTENV: "1" },
      stdio: "ignore",
    },
  );
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(base + "/healthz")).ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  throw Error("server unavailable");
});
test.after(() => server?.kill());
for (const format of ["docx", "pptx"])
  test(`${format} native repair, review, reload, export and undo`, async () => {
    const browser = await chromium.launch();
    try {
      const page = await browser.newPage({ acceptDownloads: true });
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(base);
      await page
        .locator("#pdf-file")
        .setInputFiles(path.join(__dirname, `office-example.${format}`));
      await page.getByRole("button", { name: "Open workshop" }).click();
      await page.locator(".ow").waitFor({ state: "visible" });
      await page
        .getByRole("button", { name: "2. Review and repair", exact: true })
        .click();
      await page.locator("#ow-value").fill("Reviewed training materials");
      await page.getByRole("button", { name: "Apply approved repair" }).click();
      await page.waitForFunction(
        () => document.querySelector(".ow").getAttribute("aria-busy") === null,
      );
      await page
        .locator("#ow-review-notes")
        .fill("Confirmed the title describes this document.");
      await page
        .getByRole("button", { name: "Record my review of this object" })
        .click();
      await page.waitForFunction(
        () =>
          document.querySelector("#save-status").textContent ===
          "Saved in this browser",
      );
      const route = page.url();
      await page.reload();
      await page.locator(".ow").waitFor({ state: "visible" });
      assert.equal(page.url(), route);
      assert.equal(
        await page.locator("#ow-value").inputValue(),
        "Reviewed training materials",
      );
      assert.match(
        await page.locator(".ow").innerText(),
        /Review recorded for this version/,
      );
      await page
        .getByRole("button", { name: "3. Test and export", exact: true })
        .click();
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page
          .getByRole("button", {
            name: "Download file and review report",
            exact: true,
          })
          .click(),
      ]);
      assert.match(download.suggestedFilename(), /-review.zip$/);
      await page
        .getByRole("button", { name: "Undo last repair", exact: true })
        .click();
      await page
        .getByRole("button", { name: "2. Review and repair", exact: true })
        .click();
      assert.notEqual(
        await page.locator("#ow-value").inputValue(),
        "Reviewed training materials",
      );
      assert.deepEqual(errors, []);
    } finally {
      await browser.close();
    }
  });
