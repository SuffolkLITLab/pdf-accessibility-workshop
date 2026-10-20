"""Preview-only derivatives and native block identities; never modify source bytes."""

import base64
import io
import os
import threading
import time
from urllib.parse import urlsplit
import requests
import pikepdf
from lxml import etree as ET
from .package import Package, PackageError, Conflict, q
from workshop.contracts import digest

_slots = threading.BoundedSemaphore(2)


def blocks(pkg, objects):
    indexed = {
        pkg.locate(o["target"]): o
        for o in objects
        if o["kind"] in {"paragraph", "table", "image"}
    }

    def visit(node):
        obj = indexed.get(node)
        children = [b for c in node for b in visit(c)]
        if obj:
            return [{"id": obj["id"], "kind": obj["kind"], "children": children}]
        if node.tag in {q("w", "tr"), q("w", "tc")}:
            return [
                {
                    "kind": "row" if node.tag == q("w", "tr") else "cell",
                    "children": children,
                }
            ]
        return children

    return visit(pkg.roots[pkg.main])


def instrument(source, objects):
    pkg = Package(source)
    if pkg.format != "docx":
        raise PackageError("The linked layout preview currently supports DOCX.")
    if pkg.errors:
        raise PackageError(
            "Repair the package errors before requesting a layout preview."
        )
    if any(not rel["type"].endswith("/hyperlink") for rel in pkg.external):
        raise PackageError(
            "Layout preview is unavailable for externally linked images, templates or other resources. The native block view remains available."
        )
    # Word fields can retrieve resources without an OPC external relationship.
    if any(
        any(
            term in "".join(root.itertext()).upper()
            for term in ("INCLUDEPICTURE", "INCLUDETEXT", "DDEAUTO")
        )
        for root in pkg.roots.values()
    ):
        raise PackageError(
            "Layout preview is unavailable for documents containing external-content fields."
        )
    located = [
        (o, pkg.locate(o["target"]))
        for o in objects
        if o["kind"] in {"paragraph", "table", "image"}
        and o["target"]["part"] == pkg.main
    ]
    root = pkg.roots[pkg.main]
    used = {n.get(q("w", "name")) for n in root.iter(q("w", "bookmarkStart"))}
    ids = {n.get(q("w", "id")) for n in root.iter(q("w", "bookmarkStart"))}
    index = 1
    anchors = []
    for obj, node in located:
        if obj["kind"] == "paragraph":
            first = last = node
        elif obj["kind"] == "table":
            paras = list(node.iter(q("w", "p")))
            if not paras:
                continue
            first, last = paras[0], paras[-1]
        else:
            first = next(
                (n for n in node.iterancestors() if n.tag == q("w", "p")), None
            )
            last = first
            if first is None:
                continue
        names = []
        for suffix, paragraph in [("s", first), ("e", last)]:
            name = "aw" + obj["id"] + suffix
            while name in used:
                name += "x"
            used.add(name)
            while str(index) in ids:
                index += 1
            native_id = str(index)
            ids.add(native_id)
            start = ET.Element(
                q("w", "bookmarkStart"), {q("w", "id"): native_id, q("w", "name"): name}
            )
            end = ET.Element(q("w", "bookmarkEnd"), {q("w", "id"): native_id})
            if suffix == "s":
                offset = (
                    1 if len(paragraph) and paragraph[0].tag == q("w", "pPr") else 0
                )
                paragraph.insert(offset, start)
                paragraph.insert(offset + 1, end)
            else:
                paragraph.extend([start, end])
            names.append(name)
        anchors.append(
            {
                "object_id": obj["id"],
                "start": names[0],
                "end": names[1],
                "kind": obj["kind"],
                "label": f"{obj['kind'].title()} {len(anchors) + 1}: {obj.get('table_title') or obj.get('text', '')[:70]}",
            }
        )
    pkg.touch(pkg.main)
    return pkg.write(), anchors


def convert(source, filename, expected_sha256):
    from .engine import OfficeEngine

    if digest(source) != expected_sha256:
        raise Conflict("This preview targets an older document version.")
    base = os.environ.get("GOTENBERG_URL", "").rstrip("/")
    if not base:
        raise PackageError(
            "Layout preview is not configured. You can use the native block preview."
        )
    url = urlsplit(base)
    if (
        url.scheme not in {"https", "http"}
        or not url.netloc
        or url.username
        or url.password
    ):
        raise PackageError("The preview service configuration is invalid.")
    report = OfficeEngine().inspect(source, filename)
    derivative, anchors = instrument(source, report["objects"])
    if not _slots.acquire(blocking=False):
        raise PackageError("The preview service is busy. Please retry shortly.")
    try:
        deadline = time.monotonic() + 90
        with requests.post(
            base + "/forms/libreoffice/convert",
            auth=(
                os.environ.get("GOTENBERG_USERNAME", ""),
                os.environ.get("GOTENBERG_PASSWORD", ""),
            ),
            files={
                "files": (
                    "document.docx",
                    derivative,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            data={
                "exportBookmarksToPdfDestination": "true",
                "exportFormFields": "false",
                "updateIndexes": "false",
                "exportBookmarks": "false",
            },
            timeout=(5, 90),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise PackageError(
                    "The layout preview service could not convert this document. Your DOCX is unchanged."
                )
            output = bytearray()
            for chunk in response.iter_content(65536):
                output.extend(chunk)
                if len(output) > 30 * 1024 * 1024 or time.monotonic() > deadline:
                    raise PackageError(
                        "The layout preview exceeded its size or time limit."
                    )
        content = bytes(output)
        if not content.startswith(b"%PDF-"):
            raise PackageError("The preview service did not return a PDF.")
        with pikepdf.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > 100:
                raise PackageError(
                    "Layout previews support up to 100 pages. Use the native block view for this document."
                )
        return {
            "source_sha256": expected_sha256,
            "preview_sha256": digest(content),
            "pdf_base64": base64.b64encode(content).decode(),
            "anchors": anchors,
            "purpose": "layout_preview",
            "accessibility_validation": "not_run",
        }
    except requests.RequestException:
        raise PackageError(
            "The layout preview service is unavailable. Your DOCX is unchanged; use the native block view or retry."
        ) from None
    finally:
        _slots.release()
