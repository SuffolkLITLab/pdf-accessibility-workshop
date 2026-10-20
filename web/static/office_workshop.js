import {nativePreview, pdfPreview} from "./office_preview.js";
/* Native Office review. File bytes and decisions live in browser IndexedDB. */
const roles = {body: "Body text", title: "Title", ...Object.fromEntries(Array.from({length: 9}, (_, i) => [`heading${i + 1}`, `Heading ${i + 1}`]))};
const labels = {
  set_paragraph_role: "Change heading or title level",
  set_title: "Set document title",
  set_default_language: "Set default language",
  set_text_language: "Set language for this text",
  set_alt_text: "Save approved description",
  mark_decorative: "Mark decorative",
  mark_informative: "Mark informative",
  set_table_title: "Set table name (accessible title)",
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
      if (status.textContent === "Working…") status.textContent = "Ready";
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
      ...(route === "ai-drafts" ? {signal: AbortSignal.timeout(180000)} : {}),
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
        async () => {
          Object.assign(state, state.history.pop());
          state.drafts = {};
          state.headingSelection = [];
          state.blockSelection = [];
          state.layoutPreview = null;
          state.aiDrafts = null;
          state.previewMode = "native";
          await refreshInspection();
          render();
        },
        !state.history.length,
      ),
      button("Workshop home", () => {
        root.hidden = true;
        document.getElementById("app").inert = false;
        host.onClose();
      }),
    );
    const home = element("a", null, {
      class: "aw-lab-logo", href: "/",
      "aria-label": "Accessibility workshop landing page",
    });
    home.append(element("img", null, {
      src: "/static/brand/lit-lab-logo-large.svg", alt: "Suffolk LIT Lab",
    }));
    header.append(home, brand, actions);
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
    const footer = document.getElementById("workshop-footer");
    if (footer) root.append(footer.content.cloneNode(true));
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
        `${s.problems_found || 0} problems found · ${state.receipts.length} changes · ${s.review_remaining || 0} to review · ${s.checks_unavailable || 0} checks unavailable`,
      ),
    );
    if (state.step === 0) main.append(element("p", "Automated findings and your review are recorded separately."));
    if (!state.inspection.edit_policy.editable)
      main.append(
        element("p", state.inspection.edit_policy.explanation, {
          role: "note",
        }),
      );
    if (state.step === 0) {
      aiDraftControls(main);
      main.append(
        element(
          "p",
          "Choose a finding to review it in the document.",
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
  async function refreshInspection() {
    if (state.inspection.engine_version === "office-1.2" && (state.format !== "docx" || state.inspection.blocks)) return;
    const current = await request("inspect");
    if (current.version.sha256 !== sha()) throw new Error("Inspection returned a different document version. Your saved file is unchanged.");
    current.version = state.inspection.version;
    state.inspection = current;
  }
  async function applyDecisions(decisions, focusId = "ow-selected-object") {
    const plan = await request("plan", {
      expected_sha256: sha(), decisions, idempotency_key: crypto.randomUUID(),
    });
    const result = await request("apply", { plan });
    state.history.push(snapshotVersion());
    state.working = decode(result.document_base64);
    state.inspection = result.inspection;
    state.receipts.push(result.receipt);
    state.decisions = [];
    state.external = [];
    state.drafts = {};
    state.headingSelection = [];
    state.blockSelection = [];
    state.layoutPreview = null;
    state.aiDrafts = null;
    state.previewMode = "native";
    render();
    root.querySelector("#" + focusId)?.focus();
    status.textContent = "Repair applied and rechecked. Previous review evidence is retained in history; review this new version.";
  }
  function roleSelect(id, selected = "body") {
    const select = element("select", null, {id});
    for (const [value, label] of Object.entries(roles))
      select.append(element("option", label, {value}));
    select.value = selected;
    return select;
  }
  function paragraphLocation(part) {
    if (part === "word/document.xml") return "Main document";
    const name = part.split("/").pop().replace(".xml", "");
    return name.replace(/^(header|footer)(\d+)$/, (_, label, number) => `${label === "header" ? "Header" : "Footer"} ${number}`)
      .replace("footnotes", "Footnotes").replace("endnotes", "Endnotes").replace("comments", "Comments");
  }
  function headings(parent) {
    if (state.format !== "docx") return;
    const section = element("section", null, {class: "ow-headings", "aria-labelledby": "ow-headings-title"});
    section.append(element("h3", "Headings & paragraph roles", {id: "ow-headings-title", tabindex: "-1"}),
      element("p", "Select paragraphs with the checkboxes, or highlight text below. Changes apply to the entire containing paragraphs, preserving their text and inline formatting. Paragraph styles may change their appearance."));
    const paragraphs = state.inspection.objects.filter(o => o.kind === "paragraph");
    const selected = new Set((state.headingSelection || []).filter(id => paragraphs.some(o => o.id === id)));
    const summary = element("p", "", {role: "status", "aria-live": "polite", id: "ow-heading-scope"});
    const preview = element("div", null, {class: "ow-paragraphs", tabindex: "0", "aria-label": "Read-only paragraphs for heading selection"});
    const checks = new Map();
    const update = () => {
      state.headingSelection = [...selected];
      for (const [id, check] of checks) check.checked = selected.has(id);
      summary.textContent = `${selected.size} entire paragraph(s) selected. Maximum 30 per repair.`;
      apply.disabled = !selected.size || selected.size > 30 || !state.inspection.edit_policy.editable;
      host.onStateChange();
    };
    for (const obj of paragraphs) {
      const row = element("div", null, {class: "ow-paragraph-row"});
      const check = element("input", null, {type: "checkbox", "aria-label": `Select paragraph: ${obj.label}`});
      check.onchange = () => { check.checked ? selected.add(obj.id) : selected.delete(obj.id); update(); };
      checks.set(obj.id, check);
      const content = element("div");
      content.append(element("small", `${roles[obj.role] || "Body text"} · ${paragraphLocation(obj.target.part)}`),
        element("p", obj.text || "(No paragraph text)", {"data-paragraph-id": obj.id}));
      row.append(check, content);
      preview.append(row);
    }
    const captureSelection = () => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed || !selection.rangeCount) return;
      const range = selection.getRangeAt(0);
      if (!preview.contains(range.startContainer) || !preview.contains(range.endContainer)) return;
      selected.clear();
      for (const paragraph of preview.querySelectorAll("[data-paragraph-id]")) {
        const contents = document.createRange();
        contents.selectNodeContents(paragraph);
        if (range.compareBoundaryPoints(Range.END_TO_START, contents) < 0 &&
            range.compareBoundaryPoints(Range.START_TO_END, contents) > 0)
          selected.add(paragraph.dataset.paragraphId);
      }
      update();
    };
    preview.addEventListener("mouseup", captureSelection);
    preview.addEventListener("keyup", captureSelection);
    preview.addEventListener("touchend", captureSelection);
    const level = roleSelect("ow-heading-role", state.headingRole || "heading1");
    level.onchange = () => { state.headingRole = level.value; host.onStateChange(); };
    const apply = button("Apply role to selected paragraphs", () => applyDecisions([...selected].map(object_id => ({object_id, action: "set_paragraph_role", value: level.value})), "ow-headings-title"));
    section.append(summary, element("label", "Paragraph role", {for: "ow-heading-role"}), level, apply,
      button("Clear paragraph selection", () => {selected.clear(); update();}), preview);
    parent.append(section);
    update();
  }
  function visualAndTableControls(parent) {
    if (state.format !== "docx") return;
    for (const [kind, title] of [["image", "Images: alt text & decorative"], ["table", "Table names"]]) {
      const objects = state.inspection.objects.filter(o => o.kind === kind);
      const section = element("details", null, {class: "ow-object-list", id: "ow-" + kind + "-tools"});
      section.append(element("summary", `${title} (${objects.length})`));
      if (!objects.length) section.append(element("p", `No ${kind === "image" ? "images" : "tables"} detected.`));
      for (const obj of objects) {
        const card = element("section", null, {class: "ow-object-card"});
        card.append(element("h4", obj.label));
        if (obj.preview) card.append(element("img", null, {src: obj.preview, alt: "Document image to describe", class: "ow-preview"}));
        card.append(element("p", kind === "table" ? `Table name: ${obj.table_title || "Not set"}` : obj.decorative ? "Marked decorative" : `Alt text: ${obj.value || "Not set"}`));
        card.append(button(kind === "table" ? "Edit table name" : "Edit alt text or decorative choice", () => {
          state.selected = obj.id;
          state.drafts[obj.id] = {action: kind === "table" ? "set_table_title" : "set_alt_text", value: kind === "table" ? obj.table_title || "" : obj.value || ""};
          render();
          root.querySelector("#ow-selected-object").focus();
          root.querySelector("#ow-selected-object").scrollIntoView({block: "start"});
        }));
        section.append(card);
      }
      parent.append(section);
    }
  }
  function aiDraftControls(parent) {
    if (state.format !== "docx") return;
    const section = element("section", null, {class: "ow-ai-drafts", "aria-label": "AI repair drafts"});
    const draftButton = button("Draft repairs with AI", async () => {
      draftButton.disabled = true;
      draftButton.textContent = "Drafting repairs…";
      const dialog = element("dialog", null, {
        class: "ow-ai-progress", "aria-labelledby": "ow-ai-progress-title",
        "aria-describedby": "ow-ai-progress-detail",
      });
      const heading = element("h2", "Drafting repairs…", {id: "ow-ai-progress-title", tabindex: "-1"});
      const detail = element("p", "AI is reviewing your document. This may take a minute or two.", {id: "ow-ai-progress-detail"});
      const elapsed = element("p", "Elapsed: 0 seconds", {class: "ow-ai-elapsed", "aria-hidden": "true"});
      const announcement = element("p", "", {role: "status", "aria-live": "polite"});
      dialog.append(element("span", null, {class: "ow-ai-spinner", "aria-hidden": "true"}), heading, detail,
        element("p", "You’ll review the suggestions before any changes are applied."), elapsed, announcement);
      // A running provider request cannot be cancelled server-side; keep the
      // modal open until it settles rather than imply that Escape cancels it.
      dialog.addEventListener("cancel", event => event.preventDefault());
      dialog.addEventListener("keydown", event => {
        if (event.key === "Tab") { event.preventDefault(); heading.focus(); }
      });
      document.body.append(dialog);
      dialog.showModal();
      root.inert = true;
      heading.focus();
      const started = Date.now();
      const timer = setInterval(() => {
        const seconds = Math.floor((Date.now() - started) / 1000);
        elapsed.textContent = `Elapsed: ${seconds} seconds`;
        if (seconds >= 60) announcement.textContent = "Still drafting. Larger documents can take a little longer.";
        else if (seconds >= 30) announcement.textContent = "Still reviewing your document…";
      }, 1000);
      let result;
      try {
        result = await request("ai-drafts", {expected_sha256: sha()});
        if (result.source_sha256 !== sha()) throw new Error("These drafts target a different version.");
      } catch (error) {
        if (error.name === "TimeoutError") throw new Error("AI drafting timed out. Your document is unchanged. Please try again later.");
        throw error;
      } finally {
        clearInterval(timer);
        root.inert = false;
        dialog.close();
        dialog.remove();
        draftButton.disabled = false;
        draftButton.textContent = "Draft repairs with AI";
        draftButton.focus();
      }
      state.aiDrafts = {...result, selected: []};
      render();
      root.querySelector(".ow-ai-drafts h3")?.focus();
      status.textContent = `${result.suggestions.length} repair suggestions ready for your review. No changes have been applied.`;
    }, !host.aiEnabled?.() || !state.inspection.edit_policy.editable);
    section.append(draftButton);
    const proposals = state.aiDrafts;
    if (!proposals || proposals.source_sha256 !== sha()) {
      section.append(element("small", "Sends document text and up to four image previews to OpenAI. You approve each change."));
    } else {
      section.append(element("h3", "Suggested repairs", {tabindex: "-1"}), element("p", "Choose the changes you want to apply."));
      const selected = new Set(proposals.selected || []);
      const list = element("ul", null, {class: "ow-draft-list"});
      for (const [index, suggestion] of proposals.suggestions.entries()) {
        const row = element("li");
        const label = element("label", null);
        const check = element("input", null, {type: "checkbox", "aria-label": `Approve ${labels[suggestion.action] || suggestion.action}: ${suggestion.label}`});
        check.checked = selected.has(index);
        check.onchange = () => {
          check.checked ? selected.add(index) : selected.delete(index);
          proposals.selected = [...selected];
          apply.disabled = selected.size === 0;
          host.onStateChange();
        };
        const text = element("span", null);
        const before = roles[suggestion.before] || suggestion.before;
        const after = roles[suggestion.value] || suggestion.value || "Decorative";
        text.append(element("strong", labels[suggestion.action] || suggestion.action),
          element("span", suggestion.label), element("span", `${before} → ${after}`), element("small", suggestion.reason));
        label.append(check, text); row.append(label);
        row.append(button("Show in document", () => {state.selected = suggestion.object_id; state.blockSelection = [suggestion.object_id]; state.step = 1; render(); root.querySelector("#ow-selected-object")?.focus();}));
        list.append(row);
      }
      if (!proposals.suggestions.length) section.append(element("p", "No supported repairs were proposed."));
      section.append(list);
      const apply = button("Apply selected drafts", () => applyDecisions([...selected].map(i => {
        const {object_id, action, value} = proposals.suggestions[i]; return {object_id, action, value};
      })), selected.size === 0);
      section.append(apply);
      if (proposals.review_notes.length) {
        const notes = element("details"); notes.append(element("summary", "Other items to review"));
        for (const note of proposals.review_notes) notes.append(element("p", note));
        section.append(notes);
      }
      if (proposals.excluded_proposals) section.append(element("p", `${proposals.excluded_proposals} unsupported proposals were omitted.`));
      if (proposals.objects_considered < proposals.objects_total) section.append(element("small", `AI reviewed ${proposals.objects_considered} of ${proposals.objects_total} objects. The native scan still covers the document.`));
    }
    parent.append(section);
  }
  function review(parent) {
    if (state.format !== "docx") { reviewSettings(parent); return; }
    const tools = element("nav", null, {class: "ow-tool-links", "aria-label": "DOCX repair tools"});
    for (const [id, label] of [["ow-batch-headings", "Heading levels"], ["ow-image-tools", "Image alt text"], ["ow-table-tools", "Table names"]]) {
      const link = element("a", label, {href: "#" + id});
      link.onclick = event => {event.preventDefault(); const target = root.querySelector("#" + id); target.open = true; target.querySelector("summary").focus(); target.scrollIntoView({block: "start"});};
      tools.append(link);
    }
    parent.append(tools);
    aiDraftControls(parent);
    const workspace = element("div", null, {class: "ow-workspace"});
    const viewer = element("section", null, {class: "ow-document-view", "aria-label": "Document preview"});
    const inspector = element("section", null, {class: "ow-inspector", "aria-label": "Selected block settings"});
    const toolbar = element("div", null, {class: "ow-preview-toolbar"});
    const surface = element("div", null, {class: "ow-preview-content"});
    const mark = () => {
      const selected = state.blockSelection?.length ? state.blockSelection : [state.selected];
      for (const node of surface.querySelectorAll("[data-block-id]")) {
        node.classList.toggle("ow-block-selected", selected.includes(node.dataset.blockId));
        const handle = node.matches("button") ? node : node.querySelector(".ow-block-handle");
        handle?.setAttribute("aria-pressed", String(selected.includes(node.dataset.blockId)));
      }
    };
    const choose = (id, multiple) => {
      state.selected = id;
      const ids = new Set(multiple ? state.blockSelection || [] : []);
      if (multiple && ids.has(id)) ids.delete(id); else ids.add(id);
      state.blockSelection = state.inspection.objects.filter(o => ids.has(o.id)).map(o => o.id);
      updateInspector(); mark(); host.onStateChange();
    };
    const updateInspector = () => {
      inspector.replaceChildren();

      const selected = state.blockSelection || [];
      if (selected.length > 1) inspector.append(element("p", `${selected.length} blocks selected.`));
      const merge = button("Merge adjacent blocks", async () => {
        const ids = state.blockSelection || [];
        await applyDecisions([{object_id: ids[0], action: "merge_paragraphs", value: ids}]);
      }, selected.length < 2 || !state.inspection.edit_policy.editable);
      const mergePanel = element("details");
      mergePanel.open = selected.length > 1;
      mergePanel.append(element("summary", "Merge selected paragraphs"), merge,
        element("p", "Combine adjacent text paragraphs into one block, with line breaks between their text and the first paragraph’s settings. Undo restores the original blocks."));
      if (selected.length > 1) inspector.append(mergePanel);
      const selection = element("details", null, {class: "ow-checkbox-selection"});
      selection.append(element("summary", "Select multiple paragraphs"));
      for (const obj of state.inspection.objects.filter(o => o.kind === "paragraph")) {
        const label = element("label", null, {class: "ow-select-paragraph"});
        const check = element("input", null, {type: "checkbox", "data-select-id": obj.id});
        check.checked = selected.includes(obj.id);
        check.onchange = () => {choose(obj.id, true); inspector.querySelector(".ow-checkbox-selection").open = true; inspector.querySelector(`[data-select-id="${obj.id}"]`).focus();};
        label.append(check, document.createTextNode(obj.text || "(No paragraph text)"));
        selection.append(label);
      }
      inspector.append(selection);
      reviewSettings(inspector);
    };
    const display = () => {
      surface.replaceChildren();
      if (state.previewMode === "pdf" && state.layoutPreview?.source_sha256 === sha()) {
        surface.append(element("p", "Layout preview · Click a marker to edit."));
        pdfPreview(surface, state.layoutPreview, host.pdfjsLib, choose, error => {
          surface.append(element("p", "PDF display unavailable. Choose Document blocks to continue.", {role: "alert"}));
        });
      } else {
        surface.append(element("p", "Click a block to edit · Approximate layout"));
        surface.append(nativePreview(state.inspection, state.blockSelection || [state.selected], choose));
        mark();
      }
    };
    toolbar.append(button("Document blocks", () => {state.previewMode = "native"; display();}),
      button(state.layoutPreview?.source_sha256 === sha() ? "PDF layout preview" : "Generate PDF layout preview", async () => {
        if (state.layoutPreview?.source_sha256 !== sha()) {
          const preview = await request("preview", {expected_sha256: sha()});
          if (preview.source_sha256 !== sha()) throw new Error("Preview is for a different document version.");
          state.layoutPreview = {...preview, bytes: decode(preview.pdf_base64)};
          delete state.layoutPreview.pdf_base64;
        }
        state.previewMode = "pdf"; toolbar.lastElementChild.textContent = "PDF layout preview"; display();
      }));
    viewer.append(toolbar, surface); workspace.append(viewer, inspector); parent.append(workspace);
    updateInspector(); display();
    const batch = element("details", null, {id: "ow-batch-headings"});
    batch.open = state.batchOpen || false;
    batch.ontoggle = () => {state.batchOpen = batch.open;};
    batch.append(element("summary", "Batch heading levels and text selection"));
    headings(batch); parent.append(batch);
    visualAndTableControls(parent);
  }
  function reviewSettings(parent) {
    const select = element("select", null, { id: "ow-object" });
    const picker = element("details");
    picker.append(element("summary", "Choose another block"), element("label", "Document object", { for: "ow-object" }));
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
    picker.append(select);
    parent.append(element("h3", obj.kind === "paragraph" ? "Paragraph" : obj.kind === "metadata" ? "Document title" : obj.kind === "language" ? "Language" : obj.kind[0].toUpperCase() + obj.kind.slice(1), {id: "ow-selected-object", tabindex: "-1"}));
    parent.append(picker);
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
    if (obj.style) location.append(element("p", "Native style: " + obj.style));
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
    if (state.format !== "docx") findings(parent, obj.id);
    if (obj.operations.length && state.inspection.edit_policy.editable) {
      const form = element("form", null, { class: "ow-repair" }),
        action = element("select", null, { id: "ow-action" });
      for (const op of obj.operations.filter(op => op !== "merge_paragraphs"))
        action.append(element("option", labels[op] || op, { value: op }));
      const draft = state.drafts[obj.id] || {};
      if (obj.operations.includes(draft.action)) action.value = draft.action;
      const value = element("textarea", null, {
        id: "ow-value",
        rows: "4",
        maxlength: "4000",
      });
      value.value = draft.value ?? obj.table_title ?? obj.value ?? obj.alt ?? obj.text ?? "";
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
      const role = roleSelect("ow-object-role", draft.value in roles ? draft.value : obj.role || "body");
      const roleLabel = element("label", "Heading or title level", {for: "ow-object-role"});
      const hint = element("p");
      const update = () => {
        const flag = [
          "mark_decorative",
          "mark_informative",
          "set_table_header",
        ].includes(action.value);
        value.hidden = valueLabel.hidden = flag || action.value === "set_paragraph_role";
        role.hidden = roleLabel.hidden = action.value !== "set_paragraph_role";
        check.hidden = checkLabel.hidden = action.value !== "set_table_header";
        valueLabel.textContent = action.value === "set_table_title" ? "Table name (accessible title)" : action.value === "set_alt_text" ? "Alternative text" : "Approved value or description";
        hint.textContent = action.value === "set_table_title"
          ? "Names the table without inserting a visible caption."
          : action.value === "set_alt_text"
          ? "Describe what the image communicates."
          : action.value === "set_paragraph_role"
          ? "Applies to the whole paragraph."
          : action.value === "set_table_header" && state.format === "pptx"
            ? "PowerPoint first-row formatting is limited package evidence. Verify header behavior with a screen reader in PowerPoint."
            : action.value.includes("language")
              ? "Use a language tag such as en-US or es. Setting a default preserves deliberate text overrides."
              : "";
        state.drafts[obj.id] = { action: action.value, value: action.value === "set_paragraph_role" ? role.value : value.value };
        host.onStateChange();
      };
      action.onchange = update;
      value.oninput = update;
      role.onchange = update;
      form.append(
        element("label", "Supported repair", { for: "ow-action" }),
        action,
        valueLabel,
        value,
        roleLabel,
        role,
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
            value: action.value === "set_table_header" ? true : action.value === "set_paragraph_role" ? role.value : value.value,
          };
          await applyDecisions([decision]);
        });
      };
      parent.append(form);
      update();
    }
    if (state.format === "docx") findings(parent, obj.id);
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
    const reviewNotes = element("details", null, {class: "ow-review-notes"});
    reviewNotes.open = !!previous;
    reviewNotes.append(
      element("summary", "Review notes"),
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
    parent.append(reviewNotes);
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
      await run(async () => {
        await refreshInspection();
        render();
        root.querySelector("h1").focus();
      });
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
