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

test("DOCX heading roles from text selection, persistence and undo", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(base);
    await page.locator("#pdf-file").setInputFiles(path.join(__dirname, "office-example.docx"));
    await page.getByRole("button", {name: "Open workshop"}).click();
    await page.locator(".ow").waitFor({state: "visible"});
    await page.getByRole("button", {name: "2. Review and repair", exact: true}).click();
    await page.locator("[data-paragraph-id]").nth(1).evaluate(p => {
      const range = document.createRange();
      range.setStart(p.firstChild, 2);
      range.setEnd(p.firstChild, 8);
      const selection = window.getSelection();
      selection.removeAllRanges(); selection.addRange(range);
      p.dispatchEvent(new MouseEvent("mouseup", {bubbles: true}));
    });
    assert.match(await page.locator("#ow-heading-scope").innerText(), /^1 entire/);
    await page.locator("#ow-heading-role").selectOption("heading2");
    await page.getByRole("button", {name: "Apply role to selected paragraphs", exact: true}).click();
    await page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
    assert.match(await page.locator(".ow-paragraph-row").nth(1).innerText(), /Heading 2/);
    assert.match(await page.locator("[data-paragraph-id]").nth(1).innerText(), /users\[0\]\.name/);
    await page.waitForFunction(() => document.querySelector("#save-status").textContent === "Saved in this browser");
    // Simulate a saved review from the previous engine release.
    await page.evaluate(async () => {
      const {loadReview, saveReview} = await import("/static/review_store.js");
      const record = await loadReview(location.pathname.split("/").pop());
      record.snapshot.state.inspection.engine_version = "office-1.0";
      for (const obj of record.snapshot.state.inspection.objects) {
        delete obj.role;
        obj.operations = obj.operations.filter(op => op !== "set_paragraph_role");
      }
      await saveReview(record);
    });
    await page.reload();
    await page.locator(".ow").waitFor({state: "visible"});
    await idleAfterRestore(page);
    assert.match(await page.locator(".ow-paragraph-row").nth(1).innerText(), /Heading 2/);
    await page.getByRole("button", {name: "Undo last repair"}).click();
    await page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
    assert.match(await page.locator(".ow-paragraph-row").nth(1).innerText(), /Body text/);
    // Checkboxes are the keyboard-accessible alternative to highlighting.
    await page.locator(".ow-paragraph-row input").nth(0).check();
    await page.locator(".ow-paragraph-row input").nth(1).check();
    assert.match(await page.locator("#ow-heading-scope").innerText(), /^2 entire/);
    await page.locator("#ow-heading-role").selectOption("heading1");
    await page.getByRole("button", {name: "Apply role to selected paragraphs", exact: true}).click();
    await page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
    assert.match(await page.locator(".ow-paragraph-row").nth(0).innerText(), /Heading 1/);
    assert.match(await page.locator(".ow-paragraph-row").nth(1).innerText(), /Heading 1/);
  } finally { await browser.close(); }
});

test("DOCX image alternatives and table names are discoverable and persist", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(base);
    await page.locator("#pdf-file").setInputFiles(path.join(__dirname, "semantic-example.docx"));
    await page.getByRole("button", {name: "Open workshop"}).click();
    await page.locator(".ow").waitFor({state: "visible"});
    await page.getByRole("button", {name: "2. Review and repair", exact: true}).click();
    const idle = () => page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
    await page.getByRole("link", {name: "Image alt text", exact: true}).click();
    await page.getByRole("button", {name: "Edit alt text or decorative choice"}).click();
    await page.getByLabel("Alternative text", {exact: true}).fill("Blue represents completed tasks");
    await page.getByRole("button", {name: "Apply approved repair"}).click();
    await idle();
    assert.equal(await page.locator("#ow-value").inputValue(), "Blue represents completed tasks");
    await page.locator("#ow-action").selectOption("mark_decorative");
    await page.getByRole("button", {name: "Apply approved repair"}).click();
    await idle();
    await page.getByRole("link", {name: "Image alt text", exact: true}).click();
    assert.match(await page.locator("#ow-image-tools").innerText(), /Marked decorative/);
    await page.getByRole("link", {name: "Table names", exact: true}).click();
    await page.getByRole("button", {name: "Edit table name"}).click();
    await page.getByLabel("Table name (accessible title)", {exact: true}).fill("Applicant contact details");
    await page.getByRole("button", {name: "Apply approved repair"}).click();
    await idle();
    await page.waitForFunction(() => document.querySelector("#save-status").textContent === "Saved in this browser");
    await page.reload();
    await page.locator(".ow").waitFor({state: "visible"});
    await page.getByRole("link", {name: "Table names", exact: true}).click();
    assert.match(await page.locator("#ow-table-tools").innerText(), /Applicant contact details/);
    await page.getByRole("link", {name: "Image alt text", exact: true}).click();
    assert.match(await page.locator("#ow-image-tools").innerText(), /Marked decorative/);
  } finally { await browser.close(); }
});

async function idleAfterRestore(page) {
  await page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
}
