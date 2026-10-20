import { encodePortable } from "./portable.js";
export function attachPdfEvidence(workshop, host, persist) {
  const header = document.querySelector("#a11y-workshop .aw-top-actions");
  let records = [];
  let busy = false;
  const output = document.createElement("p");
  output.setAttribute("role", "status");
  output.style.maxWidth = "30rem";
  output.style.fontSize = ".8rem";
  header.append(output);
  const digest = async (bytes) =>
    [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
      .map((n) => n.toString(16).padStart(2, "0"))
      .join("");
  async function request(route, snapshot, extra = {}) {
    const form = new FormData();
    form.append(
      "file",
      new Blob([snapshot.state.working]),
      snapshot.state.filename,
    );
    for (const [k, v] of Object.entries(extra))
      form.append(k, typeof v === "string" ? v : JSON.stringify(v));
    const r = await fetch("/api/documents/" + route, {
      method: "POST",
      body: form,
    });
    const body = await r.json();
    if (!r.ok || !body.success)
      throw Error(body.error?.message || "Request failed");
    return body.data;
  }
  function button(label, action) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "aw-btn aw-btn-secondary aw-btn-small";
    b.textContent = label;
    b.onclick = async () => {
      if (busy || workshop.isBusy()) return;
      const snapshot = workshop.checkpoint();
      if (!snapshot) return;
      busy = true;
      b.disabled = true;
      try {
        await action(snapshot);
      } catch (e) {
        host.showError(e.message);
      } finally {
        busy = false;
        b.disabled = false;
        persist();
      }
    };
    header.append(b);
  }
  button("Download review report", async (snapshot) => {
    const hash = await digest(snapshot.state.working);
    const data = await request("export", snapshot, {
      evidence: {
        source_sha256: hash,
        human_decisions: [],
        external_tests: records.filter((r) => r.source_sha256 === hash),
        portable_snapshot: encodePortable(snapshot.decisions),
      },
    });
    host.downloadBlob(
      new Blob(
        [Uint8Array.from(atob(data.bundle_base64), (c) => c.charCodeAt(0))],
        { type: "application/zip" },
      ),
      data.filename,
    );
  });
  button("Validate PDF/UA-1", async (snapshot) => {
    output.textContent = "PDF/UA-1 validation queued…";
    const job = await request("validate", snapshot, { profile: "ua1" });
    for (let i = 0; i < 150; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      const response = await fetch("/api/documents/validation/" + job.id, {
        headers: { Authorization: "Bearer " + job.token },
      });
      const body = await response.json();
      if (!body.success)
        throw Error(body.error?.message || "Validation failed");
      if (body.data.status === "complete") {
        const result = body.data.result;
        records.push(result);
        const current = workshop.checkpoint();
        const same =
          current &&
          (await digest(current.state.working)) === result.source_sha256;
        output.textContent =
          (same ? "" : "Earlier version — ") +
          result.outcome.replaceAll("_", " ") +
          ": " +
          result.detail;
        return;
      }
    }
    throw Error(
      "Validation polling timed out. No passing result was inferred.",
    );
  });
  return {
    checkpoint: () => records,
    restore: (value) => {
      records = value || [];
      output.textContent = "";
    },
    isBusy: () => busy,
  };
}
