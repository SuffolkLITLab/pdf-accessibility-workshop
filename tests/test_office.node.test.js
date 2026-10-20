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
      await page.locator(".ow-review-notes > summary").click();
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
    await page.getByRole("link", {name: "Heading levels", exact: true}).click();
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

test("DOCX native preview selects blocks and merges adjacent paragraphs with undo", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(base);
    await page.locator("#pdf-file").setInputFiles(path.join(__dirname, "semantic-example.docx"));
    await page.getByRole("button", {name: "Open workshop"}).click();
    await page.locator(".ow").waitFor({state: "visible"});
    await page.getByRole("button", {name: "2. Review and repair", exact: true}).click();
    const blocks = page.locator(".ow-document-sheet > .ow-native-block");
    const count = await blocks.count();
    await blocks.nth(0).locator(".ow-block-handle").first().click();
    assert.equal(await page.locator("#ow-action").inputValue(), "set_paragraph_role");
    await blocks.nth(1).locator(".ow-block-handle").first().click({modifiers: ["Control"]});
    await page.getByRole("button", {name: "Merge adjacent blocks", exact: true}).click();
    await idleAfterRestore(page);
    assert.equal(await blocks.count(), count - 1);
    assert.match(await blocks.first().innerText(), /Accessible workshop example\nKeep this text unchanged/);
    await page.waitForFunction(() => document.querySelector("#save-status").textContent === "Saved in this browser");
    await page.reload(); await page.locator(".ow").waitFor({state: "visible"}); await idleAfterRestore(page);
    assert.equal(await blocks.count(), count - 1);
    await page.getByRole("button", {name: "Undo last repair"}).click(); await idleAfterRestore(page);
    assert.equal(await blocks.count(), count);
  } finally { await browser.close(); }
});

test("Gotenberg PDF preview markers select native DOCX objects", {skip: !process.env.WORKSHOP_GOTENBERG_TEST}, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const errors = []; page.on("pageerror", error => errors.push(error.message));
    await page.goto(base);
    await page.locator("#pdf-file").setInputFiles(path.join(__dirname, "semantic-example.docx"));
    await page.getByRole("button", {name: "Open workshop"}).click();
    await page.locator(".ow").waitFor({state: "visible"});
    await page.getByRole("button", {name: "2. Review and repair", exact: true}).click();
    await page.getByRole("button", {name: "Generate PDF layout preview", exact: true}).click();
    await page.locator(".ow-pdf-marker").first().waitFor({state: "visible", timeout: 120000});
    const id = await page.locator(".ow-pdf-marker").first().getAttribute("data-block-id");
    await page.locator(".ow-pdf-marker").first().click();
    assert.equal(await page.locator("#ow-object").inputValue(), id);
    await page.locator("#ow-object-role").selectOption("heading1");
    await page.getByRole("button", {name: "Apply approved repair"}).click();
    await idleAfterRestore(page);
    assert.equal(await page.locator(".ow-pdf-marker").count(), 0);
    assert.ok(await page.getByRole("button", {name: "Generate PDF layout preview", exact: true}).isVisible());
    assert.deepEqual(errors, []);
  } finally { await browser.close(); }
});

for (const format of ["docx", "pptx"])
 test(`${format.toUpperCase()} AI drafts require approval, persist, and use undoable repairs`, async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route(url => url.origin === new URL(base).origin && (url.pathname === "/" || url.pathname.startsWith("/review/")), async route => {
      const response = await route.fetch();
      await route.fulfill({response, body: (await response.text()).replace('"aiEnabled": false', '"aiEnabled": true')});
    });
    let inspection, calls = 0, releaseDraft;
    const pendingDraft = new Promise(resolve => { releaseDraft = resolve; });
    page.on("response", async response => {
      if (response.url().endsWith("/api/documents/inspect")) inspection = (await response.json()).data;
    });
    await page.route("**/api/documents/ai-drafts", async route => {
      calls++;
      if (calls > 1) {
        await route.fulfill({status: 429, json: {success: false, error: {message: "AI allowance reached. Manual editing is still available."}}});
        return;
      }
      await pendingDraft;
      const title = inspection.objects.find(o => o.kind === "metadata");
      await route.fulfill({json: {success: true, data: {
        source_sha256: inspection.version.sha256, draft: true,
        suggestions: [{object_id: title.id, action: "set_title", value: "Reviewed AI title", before: title.value || "(not set)", label: "Document title", reason: "Use the visible title.", draft: true}],
        review_notes: [], objects_considered: inspection.objects.length, objects_total: inspection.objects.length,
      }}});
    });
    await page.goto(base);
    await page.locator("#pdf-file").setInputFiles(path.join(__dirname, `office-example.${format}`));
    await page.getByRole("button", {name: "Open workshop"}).click();
    await page.locator(".ow").waitFor({state: "visible"});
    assert.equal(calls, 0);
    await page.getByRole("button", {name: "Draft repairs with AI", exact: true}).click();
    const progress = page.locator("dialog.ow-ai-progress");
    await progress.waitFor({state: "visible"});
    assert.equal(await page.getByRole("button", {name: "Drafting repairs…", includeHidden: true}).isDisabled(), true);
    assert.equal(await page.locator(".ow").evaluate(node => node.inert), true);
    assert.equal(await progress.evaluate(node => node.contains(document.activeElement)), true);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Tab");
    assert.equal(await progress.isVisible(), true);
    assert.equal(await progress.evaluate(node => node.contains(document.activeElement)), true);
    await page.emulateMedia({reducedMotion: "reduce"});
    assert.equal(await page.locator(".ow-ai-spinner").evaluate(node => getComputedStyle(node).animationName), "none");
    await page.emulateMedia({reducedMotion: "no-preference"});
    assert.equal(await page.locator(".ow-ai-spinner").evaluate(node => getComputedStyle(node).animationName), "ow-ai-spin");
    releaseDraft();
    const choice = page.locator(".ow-draft-list input[type=checkbox]");
    await choice.waitFor();
    assert.equal(await choice.isChecked(), false);
    assert.equal(await progress.count(), 0);
    assert.equal(await page.locator(".ow").evaluate(node => node.inert), false);
    assert.equal(await page.getByRole("button", {name: "Apply selected drafts"}).isDisabled(), true);
    await choice.check();
    await page.waitForFunction(() => document.querySelector("#save-status").textContent === "Saved in this browser");
    await page.reload();
    await choice.waitFor();
    assert.equal(await choice.isChecked(), true);
    assert.equal(calls, 1);
    await page.getByRole("button", {name: "Apply selected drafts"}).click();
    await page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
    assert.equal(await choice.count(), 0);
    await page.getByRole("button", {name: "2. Review and repair", exact: true}).click();
    assert.equal(await page.locator("#ow-value").inputValue(), "Reviewed AI title");
    await page.getByRole("button", {name: "Undo last repair"}).click();
    await page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
    assert.notEqual(await page.locator("#ow-value").inputValue(), "Reviewed AI title");
    await page.getByRole("button", {name: "Draft repairs with AI", exact: true}).click();
    await page.waitForFunction(() => document.querySelector(".ow > [role=status]").textContent.includes("AI allowance reached"));
    assert.equal(await progress.count(), 0);
    assert.equal(await page.locator(".ow").evaluate(node => node.inert), false);
    assert.equal(await page.getByRole("button", {name: "Draft repairs with AI", exact: true}).isEnabled(), true);
  } finally { await browser.close(); }
});

test("PPTX slide objects expose manual title, image and table repairs", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(base);
    await page.locator("#pdf-file").setInputFiles(path.join(__dirname, "presentation-example.pptx"));
    await page.getByRole("button", {name: "Open workshop"}).click();
    await page.getByRole("button", {name: "2. Review and repair", exact: true}).click();
    const choose = async name => {
      await page.locator(".ow-slide-list").getByRole("button", {name}).click();
    };
    const apply = async () => {
      await page.getByRole("button", {name: "Apply approved repair", exact: true}).click();
      await page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
    };
    await choose(/^Title:/);
    await page.locator("#ow-action").selectOption("set_existing_title");
    await page.locator("#ow-value").fill("Accessible workshop overview");
    await apply();
    assert.match(await page.locator(".ow-slide-list").innerText(), /Accessible workshop overview/);
    await choose(/^Image:/);
    await page.locator("#ow-action").selectOption("set_alt_text");
    await page.locator("#ow-value").fill("Blue rectangle legend key");
    await apply();
    assert.equal(await page.locator("#ow-value").inputValue(), "Blue rectangle legend key");
    await page.locator("#ow-action").selectOption("mark_decorative");
    await apply();
    await choose(/^Table:/);
    await page.locator("#ow-action").selectOption("set_table_title");
    await page.locator("#ow-value").fill("Review responsibilities");
    await apply();
    await page.locator("#ow-action").selectOption("set_table_title");
    assert.equal(await page.locator("#ow-value").inputValue(), "Review responsibilities");
    await page.locator("#ow-action").selectOption("set_table_header");
    await page.locator("#ow-table-confirm").check();
    await apply();
    await page.waitForFunction(() => document.querySelector("#save-status").textContent === "Saved in this browser");
    await page.reload();
    await page.locator(".ow-slide-list").waitFor();
    assert.match(await page.locator(".ow-slide-list").innerText(), /Accessible workshop overview/);
    await page.getByRole("button", {name: "Undo last repair"}).click();
    await page.waitForFunction(() => document.querySelector(".ow").getAttribute("aria-busy") === null);
    await page.locator("#ow-action").selectOption("set_table_title");
    assert.equal(await page.locator("#ow-value").inputValue(), "Review responsibilities");
  } finally { await browser.close(); }
});
