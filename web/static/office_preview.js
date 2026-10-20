/* Native identities drive both the simulated view and PDF destination markers. */
function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== null) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}
export function nativePreview(report, selected, onSelect) {
  const byId = new Map(report.objects.map(o => [o.id, o]));
  const sheet = el("div", null, {class: "ow-document-sheet", "aria-label": "Document block preview"});
  const draw = (block, parent) => {
    const obj = byId.get(block.id);
    if (!obj) {
      const node = el(block.kind === "row" ? "tr" : block.kind === "cell" ? "td" : "div", null);
      for (const child of block.children || []) draw(child, node);
      parent.append(node); return;
    }
    const tag = block.kind === "table" ? "div" : "section";
    const node = el(tag, null, {class: "ow-native-block", "data-block-id": obj.id});
    const choose = el("button", `${obj.kind === "paragraph" ? obj.role?.replace("heading", "Heading ") || "Body text" : obj.kind === "table" ? obj.table_title || "Table" : "Image"} settings`,
      {type: "button", class: "ow-block-handle", "aria-pressed": String(selected.includes(obj.id))});
    choose.onclick = event => {event.stopPropagation(); onSelect(obj.id, event.ctrlKey || event.metaKey || event.shiftKey);};
    node.append(choose);
    if (block.kind === "paragraph") {
      const role = obj.role || "body";
      const heading = role.startsWith("heading") ? Math.min(6, Number(role.slice(7))) : 0;
      const content = el(heading ? `h${heading}` : "p", obj.text || "", {class: role === "title" ? "ow-document-title" : ""});
      node.append(content);
      for (const child of block.children || []) draw(child, node);
      if (!obj.text && !block.children?.length) content.textContent = "(No paragraph text)";
    } else if (block.kind === "image") {
      if (obj.preview) node.append(el("img", null, {src: obj.preview, alt: obj.decorative ? "" : obj.value || "Image awaiting description"}));
      else node.append(el("p", "Image preview unavailable"));
      if (obj.decorative) node.append(el("small", "Decorative"));
    } else {
      const table = el("table", null);
      for (const child of block.children || []) draw(child, table);
      node.append(table);
    }
    node.onclick = event => {
      if (event.target.closest("[data-block-id]") !== node) return;
      if (window.getSelection()?.toString()) return;
      onSelect(obj.id, event.ctrlKey || event.metaKey || event.shiftKey);
    };
    parent.append(node);
  };
  for (const block of report.blocks || []) draw(block, sheet);
  return sheet;
}

export async function pdfPreview(parent, preview, pdfjs, onSelect, onError) {
  let document;
  try {
    document = await pdfjs.getDocument({data: preview.bytes.slice()}).promise;
    const destinations = [];
    for (const anchor of preview.anchors) {
      const start = await document.getDestination(anchor.start);
      if (!start || start[1]?.name !== "XYZ") continue;
      const page = typeof start[0] === "number" ? start[0] : await document.getPageIndex(start[0]);
      destinations.push({...anchor, page, x: start[2], y: start[3]});
    }
    if (!parent.isConnected) {await document.destroy(); return;}
    if (!destinations.length) parent.append(el("p", "This converter did not supply block anchors. Use the Document blocks view to edit; this PDF shows layout only."));
    const pager = el("div", null, {class: "ow-preview-pager"});
    const label = el("span", "");
    const previous = el("button", "Previous page", {type: "button"});
    const next = el("button", "Next page", {type: "button"});
    const surface = el("div", null, {class: "ow-pdf-surface"});
    const zoomIn = el("button", "+", {type: "button", "aria-label": "Zoom in PDF preview"});
    const zoomOut = el("button", "−", {type: "button", "aria-label": "Zoom out PDF preview"});
    let pageNumber = 1, rendering = false, zoom = 1;
    async function show() {
      if (rendering || !parent.isConnected) return;
      rendering = true; previous.disabled = next.disabled = zoomIn.disabled = zoomOut.disabled = true;
      try {
        const page = await document.getPage(pageNumber);
        const original = page.getViewport({scale: 1});
        const width = Math.max(260, Math.min(850, parent.clientWidth - 30));
        const viewport = page.getViewport({scale: zoom * width / original.width});
        surface.replaceChildren();
        surface.style.width = `${viewport.width}px`; surface.style.height = `${viewport.height}px`;
        const canvas = el("canvas", null, {"aria-label": `Rendered page ${pageNumber}. Use block markers or Document blocks to select content.`});
        canvas.width = Math.ceil(viewport.width * 1.5); canvas.height = Math.ceil(viewport.height * 1.5);
        canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`;
        surface.append(canvas);
        await page.render({canvasContext: canvas.getContext("2d"), viewport, transform: [1.5, 0, 0, 1.5, 0, 0]}).promise;
        const occupied = new Map();
        for (const anchor of destinations.filter(a => a.page === pageNumber - 1)) {
          const [x, y] = viewport.convertToViewportPoint(anchor.x ?? 0, anchor.y ?? original.height);
          const row = Math.round(y / 12), offset = occupied.get(row) || 0; occupied.set(row, offset + 1);
          const button = el("button", anchor.kind === "paragraph" ? "¶" : anchor.kind === "table" ? "▦" : "▧", {
            type: "button", class: "ow-pdf-marker", "data-block-id": anchor.object_id,
            "aria-label": `Select ${anchor.label || anchor.kind}`,
          });
          button.style.left = `${Math.max(0, Math.min(viewport.width - 24, x - 24 - offset * 25))}px`;
          button.style.top = `${Math.max(0, Math.min(viewport.height - 24, y - 18))}px`;
          button.onclick = event => onSelect(anchor.object_id, event.ctrlKey || event.metaKey || event.shiftKey);
          surface.append(button);
        }
        label.textContent = `Page ${pageNumber} of ${document.numPages}`;
      } finally { rendering = false; previous.disabled = pageNumber === 1; next.disabled = pageNumber === document.numPages; zoomIn.disabled = zoom >= 2; zoomOut.disabled = zoom <= .75; }
    }
    previous.onclick = () => {pageNumber--; show().catch(onError);};
    next.onclick = () => {pageNumber++; show().catch(onError);};
    zoomIn.onclick = () => {zoom += .25; show().catch(onError);};
    zoomOut.onclick = () => {zoom -= .25; show().catch(onError);};
    pager.append(previous, label, next, zoomOut, zoomIn); parent.append(pager, surface);
    await show();
    const observer = new MutationObserver(() => {
      if (!parent.isConnected) {observer.disconnect(); document.destroy();}
    });
    observer.observe(window.document.body, {childList: true, subtree: true});
  } catch (error) {
    if (parent.isConnected) onError(error);
    await document?.destroy();
  }
}
