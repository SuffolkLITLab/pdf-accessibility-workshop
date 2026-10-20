/* Native Office review. File bytes and decisions live in browser IndexedDB. */
const labels = {
  set_title: "Set document title",
  set_default_language: "Set default language",
  set_text_language: "Set language for this text",
  set_alt_text: "Save approved description",
  mark_decorative: "Mark decorative",
  mark_informative: "Mark informative",
  set_table_header: "Confirm first row as headers",
  set_link_text: "Change link text",
  set_existing_title: "Change existing slide title",
};
const decode = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
function element(tag, text, attrs = {}) {
  const el = document.createElement(tag);
  if (text !== null) el.textContent = text;
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  return el;
}
export function createOfficeWorkshop(host) {
  let state = null,
    busy = false;
  const root = element("section", null, {
    class: "aw ow",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "ow-title",
    hidden: "",
  });
  document.body.append(root);
  const status = element("p", "", { role: "status", "aria-live": "polite" });
  function button(text, fn, disabled = false) {
    const b = element("button", text, {
      type: "button",
      class: "aw-btn aw-btn-secondary",
    });
    b.disabled = disabled;
    b.onclick = () => run(fn);
    return b;
  }
  async function run(fn) {
    if (busy) return;
    busy = true;
    root.setAttribute("aria-busy", "true");
    status.textContent = "Working…";
    try {
      await fn();
      status.textContent = "Ready";
    } catch (e) {
      status.textContent = e.message;
      host.showError(e.message);
    } finally {
      busy = false;
      root.removeAttribute("aria-busy");
      host.onStateChange();
    }
  }
  async function request(route, extra = {}) {
    const form = new FormData();
    form.append("file", new Blob([state.working]), state.filename);
    for (const [key, value] of Object.entries(extra))
      form.append(
        key,
        typeof value === "string" ? value : JSON.stringify(value),
      );
    const response = await fetch("/api/documents/" + route, {
      method: "POST",
      body: form,
    });
    let body;
    try {
      body = await response.json();
    } catch {
      throw new Error(
        "The server could not finish this request. Your previous version is still available.",
      );
    }
    if (!response.ok || !body.success)
      throw new Error(body.error?.message || "Request failed.");
    return body.data;
  }
  function sha() {
    return state.inspection.version.sha256;
  }
  function snapshotVersion() {
    return structuredClone({
      working: state.working,
      inspection: state.inspection,
      decisions: state.decisions,
      external: state.external,
      receipts: state.receipts,
    });
  }
  function render() {
    root.replaceChildren();
    const header = element("header", null, { class: "aw-topbar" });
    const brand = element("div");
    brand.append(
      element("h1", "Document accessibility workshop", {
        id: "ow-title",
        class: "aw-product",
        tabindex: "-1",
      }),
      element(
        "p",
        state.filename + " · " + state.inspection.format.toUpperCase(),
      ),
    );
    const actions = element("div", null, { class: "aw-top-actions" });
    actions.append(
      element("span", "", { role: "status", "data-office-save-status": "" }),
      button(
        "Undo last repair",
        () => {
          Object.assign(state, state.history.pop());
          state.drafts = {};
          render();
        },
        !state.history.length,
      ),
      button("Choose document", () => {
        root.hidden = true;
        document.getElementById("app").inert = false;
        host.onClose();
      }),
    );
    header.append(brand, actions);
    root.append(header);
    const body = element("div", null, { class: "aw-body" }),
      nav = element("nav", null, {
        class: "aw-rail",
        "aria-label": "Workshop stages",
      }),
      main = element("main", null, { class: "aw-main ow-content" });
    ["Find problems", "Review and repair", "Test and export"].forEach(
      (label, index) => {
        const b = button(`${index + 1}. ${label}`, () => {
          state.step = index;
          render();
          root.querySelector("main h2")?.focus();
        });
        if (state.step === index) b.setAttribute("aria-current", "step");
        nav.append(b);
      },
    );
    body.append(nav, main);
    root.append(body);
    main.append(
      element(
        "h2",
        ["Find problems", "Review and repair", "Test and export"][state.step],
        { tabindex: "-1" },
      ),
    );
    const s = state.inspection.summary;
    main.append(
      element(
        "p",
        `${s.problems_found || 0} problems found · ${state.receipts.length} repairs applied · ${s.review_remaining || 0} machine-identified review items · ${s.checks_unavailable || 0} checks unavailable`,
      ),
    );
    main.append(
      element(
        "p",
        "Automated findings, your review, external checks, and reader testing are separate evidence. A review decision does not erase a failing check.",
      ),
    );
    if (!state.inspection.edit_policy.editable)
      main.append(
        element("p", state.inspection.edit_policy.explanation, {
          role: "note",
        }),
      );
    if (state.step === 0) {
      main.append(
        element(
          "p",
          "Office files are inspected without automatic changes or AI calls. Select a finding to review its native object.",
        ),
      );
      findings(main);
      coverage(main);
      main.append(
        button("Review document objects", () => {
          state.step = 1;
          render();
        }),
      );
    } else if (state.step === 1) review(main);
    else exportView(main);
    root.append(status);
    host.onStateChange();
  }
  function findings(parent, objectId = null) {
    const list = element("ul", null, { class: "ow-findings" });
    const rows = state.inspection.findings.filter(
      (f) => objectId === null || f.object_id === objectId,
    );
    for (const f of rows) {
      const item = element("li");
      item.append(
        element("strong", f.outcome.replaceAll("_", " ") + " · " + f.rule_id.split(".").slice(1).join(" ")),
        element("p", f.message),
        element("small", f.location_label),
      );
      if (f.object_id && objectId === null)
        item.append(
          button("Review this object", () => {
            state.selected = f.object_id;
            state.step = 1;
            render();
          }),
        );
      list.append(item);
    }
    if (!rows.length)
      list.append(
        element(
          "li",
          "No automated finding for this object. Meaning and usability still require review.",
        ),
      );
    parent.append(list);
  }
  function coverage(parent) {
    const details = element("details"),
      sum = element("summary", "Coverage and unavailable checks");
    details.append(sum);
    const list = element("ul");
    for (const c of state.inspection.coverage)
      list.append(
        element(
          "li",
          `${c.capability || c.part}: ${c.outcome.replaceAll("_", " ")} — ${c.detail}`,
        ),
      );
    details.append(list);
    parent.append(details);
  }
  function review(parent) {
    parent.append(
      element(
        "p",
        "This semantic view follows native document structure. It is not a rendered page or slide preview. Confirm layout, reading order, and behavior in Word or PowerPoint.",
      ),
    );
    const select = element("select", null, { id: "ow-object" });
    parent.append(element("label", "Document object", { for: "ow-object" }));
    for (const obj of state.inspection.objects)
      select.append(
        element("option", `${obj.kind}: ${obj.label}`, { value: obj.id }),
      );
    const obj =
      state.inspection.objects.find((o) => o.id === state.selected) ||
      state.inspection.objects[0];
    if (!obj) return;
    state.selected = obj.id;
    select.value = obj.id;
    select.onchange = () => {
      state.selected = select.value;
      render();
    };
    parent.append(select);
    parent.append(element("h3", obj.label));
    const location = element("details");
    location.append(element("summary", "Technical location"), element("p", `${obj.target.part} · object ${obj.target.object_id || obj.target.element_path || "document root"}`));
    parent.append(location);
    if (obj.preview)
      parent.append(
        element("img", null, {
          src: obj.preview,
          alt: "Selected document image for author review",
          class: "ow-preview",
        }),
      );
    if (obj.style)
      parent.append(element("p", "Native paragraph style: " + obj.style));
    if (obj.text) parent.append(element("pre", obj.text, { class: "ow-text" }));
    if (obj.rows) {
      const table = element("table");
      for (const row of obj.rows) {
        const tr = element("tr");
        for (const cell of row) tr.append(element("td", cell));
        table.append(tr);
      }
      parent.append(table);
    }
    findings(parent, obj.id);
    if (obj.operations.length && state.inspection.edit_policy.editable) {
      const form = element("form", null, { class: "ow-repair" }),
        action = element("select", null, { id: "ow-action" });
      for (const op of obj.operations)
        action.append(element("option", labels[op] || op, { value: op }));
      const draft = state.drafts[obj.id] || {};
      if (obj.operations.includes(draft.action)) action.value = draft.action;
      const value = element("textarea", null, {
        id: "ow-value",
        rows: "4",
        maxlength: "4000",
      });
      value.value = draft.value ?? obj.value ?? obj.alt ?? obj.text ?? "";
      const valueLabel = element("label", "Approved value or description", {
        for: "ow-value",
      });
      const check = element("input", null, {
          type: "checkbox",
          id: "ow-table-confirm",
        }),
        checkLabel = element(
          "label",
          "I confirm this is a simple data table and its first row contains meaningful column headings.",
          { for: "ow-table-confirm" },
        );
      const hint = element("p");
      const update = () => {
        const flag = [
          "mark_decorative",
          "mark_informative",
          "set_table_header",
        ].includes(action.value);
        value.hidden = valueLabel.hidden = flag;
        check.hidden = checkLabel.hidden = action.value !== "set_table_header";
        hint.textContent =
          action.value === "set_table_header" && state.format === "pptx"
            ? "PowerPoint first-row formatting is limited package evidence. Verify header behavior with a screen reader in PowerPoint."
            : action.value.includes("language")
              ? "Use a language tag such as en-US or es. Setting a default preserves deliberate text overrides."
              : "";
        state.drafts[obj.id] = { action: action.value, value: value.value };
        host.onStateChange();
      };
      action.onchange = update;
      value.oninput = update;
      form.append(
        element("label", "Supported repair", { for: "ow-action" }),
        action,
        valueLabel,
        value,
        check,
        checkLabel,
        hint,
      );
      const submit = element("button", "Apply approved repair", {
        type: "submit",
        class: "aw-btn aw-btn-primary",
      });
      form.append(submit);
      form.onsubmit = (event) => {
        event.preventDefault();
        run(async () => {
          if (action.value === "set_table_header" && !check.checked)
            throw new Error(
              "Confirm the table meaning before changing its header setting.",
            );
          const decision = {
            object_id: obj.id,
            action: action.value,
            value: action.value === "set_table_header" ? true : value.value,
          };
          const plan = await request("plan", {
            expected_sha256: sha(),
            decisions: [decision],
            idempotency_key: crypto.randomUUID(),
          });
          const result = await request("apply", { plan });
          state.history.push(snapshotVersion());
          state.working = decode(result.document_base64);
          state.inspection = result.inspection;
          state.receipts.push(result.receipt);
          state.decisions = [];
          state.external = [];
          state.drafts = {};
          render();
          status.textContent =
            "Repair applied and rechecked. Previous review evidence is retained in history; review this new version.";
        });
      };
      parent.append(form);
      update();
    }
    const notes = element("textarea", null, {
      id: "ow-review-notes",
      rows: "3",
      placeholder: "What did you review? What remains unresolved?",
    });
    const previous = state.decisions.find((d) => d.object_id === obj.id);
    notes.value = previous?.notes || state.drafts["notes:" + obj.id] || "";
    notes.oninput = () => {
      state.drafts["notes:" + obj.id] = notes.value;
      host.onStateChange();
    };
    parent.append(
      element("h3", "Human review"),
      element("label", "Review notes", { for: "ow-review-notes" }),
      notes,
      button("Record my review of this object", () => {
        if (!notes.value.trim())
          throw new Error(
            "Describe what you reviewed before recording a decision.",
          );
        state.decisions = state.decisions.filter((d) => d.object_id !== obj.id);
        state.decisions.push({
          object_id: obj.id,
          target: obj.target,
          source_sha256: sha(),
          outcome: "reviewed",
          notes: notes.value,
          date: new Date().toISOString(),
        });
        render();
      }),
    );
    if (previous)
      parent.append(
        element("p", "Review recorded for this version: " + previous.notes),
      );
    const globalTasks = state.inspection.findings.filter(
      (f) => !f.object_id && f.outcome === "needs_review",
    );
    if (globalTasks.length) {
      const group = element("details");
      group.append(element("summary", "Document-wide review tasks"));
      for (const task of globalTasks) group.append(element("p", task.message));
      const whole = element("textarea", null, {
        id: "ow-whole-review",
        rows: "3",
      });
      whole.value = state.drafts.whole || "";
      whole.oninput = () => {
        state.drafts.whole = whole.value;
        host.onStateChange();
      };
      group.append(
        element(
          "label",
          "What did you review across the document? Record unresolved issues too.",
          { for: "ow-whole-review" },
        ),
        whole,
        button("Record document-wide review", () => {
          if (!whole.value.trim())
            throw new Error("Describe the review you actually completed.");
          state.decisions.push({
            source_sha256: sha(),
            scope: "document",
            outcome: "reviewed",
            notes: whole.value,
            date: new Date().toISOString(),
          });
          state.drafts.whole = "";
          render();
        }),
      );
      parent.append(group);
    }
  }
  function exportView(parent) {
    parent.append(
      element(
        "p",
        `${state.decisions.length} human review records are saved for this version. Other objects and manual tasks remain unreviewed. Native application and assistive-technology checks are not performed by this service.`,
      ),
    );
    parent.append(
      button("Reinspect current version", async () => {
        const next = await request("inspect");
        next.version = state.inspection.version;
        state.inspection = next;
        render();
      }),
    );
    coverage(parent);
    const notes = element("textarea", null, {
      id: "ow-external",
      rows: "4",
      placeholder:
        "Application and version, assistive technology, steps, result, and remaining problems",
    });
    notes.value = state.drafts.external || "";
    notes.oninput = () => {
      state.drafts.external = notes.value;
      host.onStateChange();
    };
    parent.append(
      element("h3", "Record external testing"),
      element("label", "Actual testing performed on this version", {
        for: "ow-external",
      }),
      notes,
      button("Record external test", () => {
        if (!notes.value.trim())
          throw new Error("Enter the actual test and its result.");
        state.external.push({
          source_sha256: sha(),
          outcome: "author_recorded",
          notes: notes.value,
          date: new Date().toISOString(),
        });
        state.drafts.external = "";
        render();
      }),
    );
    for (const test of state.external) parent.append(element("p", test.notes));
    parent.append(
      element("h3", "Download"),
      button("Download current native file", () =>
        host.downloadBlob(new Blob([state.working]), state.filename),
      ),
      button("Download original", () =>
        host.downloadBlob(
          new Blob([state.original]),
          "original-" + state.filename,
        ),
      ),
      button("Download file and review report", async () => {
        const result = await request("export", {
          evidence: {
            source_sha256: sha(),
            version: state.inspection.version,
            human_decisions: state.decisions,
            external_tests: state.external,
            repair_receipts: state.receipts,
          },
        });
        host.downloadBlob(
          new Blob([decode(result.bundle_base64)], { type: "application/zip" }),
          result.filename,
        );
      }),
    );
    parent.append(
      element(
        "p",
        "The ZIP includes the exact native file, a readable HTML report, and a portable JSON manifest. PDF conversions must be inspected independently.",
      ),
    );
    findings(parent);
  }
  return {
    async open({ filename, bytes }) {
      state = {
        filename,
        original: bytes,
        working: bytes,
        history: [],
        receipts: [],
        decisions: [],
        external: [],
        drafts: {},
        step: 0,
      };
      await run(async () => {
        state.inspection = await request("inspect");
        state.format = state.inspection.format;
        root.hidden = false;
        document.getElementById("app").inert = true;
        render();
        root.querySelector("h1").focus();
      });
    },
    async restore(snapshot) {
      state = snapshot.state;
      root.hidden = false;
      document.getElementById("app").inert = true;
      render();
      root.querySelector("h1").focus();
    },
    checkpoint() {
      return state?.inspection && !busy
        ? { schema: 1, format: state.format, state: structuredClone(state) }
        : null;
    },
    isBusy() {
      return busy;
    },
  };
}
