import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.min.mjs";
import { createAccessibilityWorkshop } from "/assets/pdf_accessibility_workshop.js";

import { saveReview, loadReview, deleteReview, listReviews } from "./review_store.js";

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.0.379/pdf.worker.min.mjs";
const config = JSON.parse(document.getElementById("workshop-config").textContent);
const input = document.getElementById("pdf-file");
const notice = document.getElementById("notice");
function message(text) {
  notice.querySelector("span").textContent = text;
  notice.hidden = false;
}
notice.querySelector("button").addEventListener("click", () => {
  notice.hidden = true;
});
let reviewId = null;
let pendingSaves = 0;
let saveFailed = false;
let saveQueued = false;
const saveStatus = document.getElementById("save-status");
function persist() {
  if (!reviewId || saveQueued) return;
  saveQueued = true;
  queueMicrotask(async () => {
    saveQueued = false;
    const snapshot = workshop.checkpoint();
    if (!snapshot) return;
    pendingSaves += 1;
    saveStatus.textContent = "Saving in this browser…";
    try {
      await saveReview({id: reviewId, filename: snapshot.state.filename,
        updated: Date.now(), snapshot});
      saveFailed = false;
      saveStatus.textContent = "Saved in this browser";
    } catch (_error) {
      saveFailed = true;
      saveStatus.textContent = "Not saved — export to keep your work";
      message("Your browser could not save this review, possibly because storage is full or unavailable. Export your PDF before closing.");
    } finally { pendingSaves -= 1; }
  });
}
async function showSavedReviews() {
  const section = document.getElementById("saved-reviews");
  const list = section.querySelector("ul");
  list.replaceChildren();
  try {
    const records = await listReviews();
    section.hidden = !records.length;
    for (const record of records.sort((a,b) => b.updated-a.updated)) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = `/review/${record.id}`;
      link.textContent = record.filename;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete saved review";
      remove.setAttribute("aria-label", `Delete saved review of ${record.filename}`);
      remove.onclick = async () => {
        if (!confirm(`Delete the saved review of ${record.filename} from this browser?`)) return;
        try { await deleteReview(record.id); await showSavedReviews(); }
        catch (_error) { message("The saved review could not be deleted. Please retry."); }
      };
      item.append(link, remove); list.append(item);
    }
  } catch (_error) {
    message("Browser storage is unavailable. You can still review a PDF, but export it before closing.");
  }
}
const workshop = createAccessibilityWorkshop({
  pdfjsLib,
  apiUrl: (path) => path,
  parseApiResponse: async (response) => {
    if (!response.headers.get("content-type")?.includes("application/json")) {
      throw new Error("The server could not finish this request. Please retry.");
    }
    return response.json();
  },
  downloadBlob: (blob, name) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  },
  showError: message,
  showSuccess: message,
  aiEnabled: () => config.aiEnabled,
  model: () => config.model,
  closePrompt:
    "Return to your saved reviews? Your latest saved work stays in this browser.",
  onStateChange: persist,
  onClose: () => {
    persist();
    history.replaceState(null, "", "/");
    showSavedReviews();
    input.focus();
  },
});
document.getElementById("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = input.files[0];
  if (!file) return;
  if (file.size > 30 * 1024 * 1024) {
    message("Choose a PDF smaller than 30 MB.");
    return;
  }
  notice.hidden = true;
  reviewId = crypto.randomUUID();
  history.replaceState(null, "", `/review/${reviewId}`);
  await workshop.open({
    signature: reviewId,
    getPdf: async () => ({
      filename: file.name,
      bytes: new Uint8Array(await file.arrayBuffer()),
    }),
  });
});
window.addEventListener("beforeunload", (event) => {
  if (pendingSaves || saveQueued || saveFailed || workshop.isBusy()) event.preventDefault();
});

const routeId = location.pathname.match(/^\/review\/([0-9a-f-]{36})$/)?.[1];
if (routeId) {
  reviewId = routeId;
  try {
    const record = await loadReview(reviewId);
    if (!record) {
      message("This review is not saved in this browser. Open the PDF below to start a new review.");
      history.replaceState(null, "", "/");
      await showSavedReviews();
    } else await workshop.restore(record.snapshot);
  } catch (_error) {
    message("The saved review could not be restored. It has not been deleted; you can retry or open another PDF.");
    history.replaceState(null, "", "/");
    await showSavedReviews();
  }
} else await showSavedReviews();
