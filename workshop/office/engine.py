"""Native inventories, evidence and conservative Office editing capabilities."""

from .docx_headings import paragraph_role

import base64
from collections import Counter
import io
from pathlib import PurePosixPath
import re
import tempfile
import zipfile
from lxml import etree as ET
from workshop.contracts import (
    DocumentVersion,
    ENGINE_VERSION,
    RULE_REFERENCES,
    SCHEMA_VERSION,
    digest,
    summary,
)
from .package import Package, PackageError, NS, q, local, descendants, text, on
from workshop.vendor.dayamlchecker.docx_accessibility import (
    DocxAccessibilityOptions,
    check_docx_accessibility,
    check_docx_review_markup,
)
from workshop.vendor.dayamlchecker.messages import Severity, MESSAGE_DEFINITIONS

DOCX_RULES = {
    "EA540": "docx-unreadable",
    "EA541": "image-alt-missing",
    "EA542": "object-alt-missing",
    "EA543": "hyperlink-empty",
    "EA544": "contrast-explicit-fail",
    "EA545": "document-language-missing",
    "WA546": "table-merged-cells",
    "WA547": "decorative-image-has-alt",
    "WA548": "image-alt-placeholder",
    "WA549": "link-raw-url",
    "WA550": "link-ambiguous",
    "WA551": "table-layout-suspected",
    "WA552": "table-no-header-row",
    "WA553": "floating-object-detected",
    "WA554": "text-box-detected",
    "WA555": "heading-empty",
    "WA556": "heading-none",
    "WA557": "heading-order-starts-too-low",
    "WA558": "heading-skipped-level",
    "WA559": "image-only-document",
    "WA560": "color-only-risk",
    "IA561": "document-title-missing",
    "IA562": "filename-not-descriptive",
    "IA563": "all-caps-heading",
    "IA564": "long-alt-text",
    "IA565": "many-empty-paragraphs",
    "IA566": "manual-numbering-detected",
    "IA567": "link-same-url-different-text",
}


def child(node, name):
    return (
        next((el for el in node if local(el) == name), None)
        if node is not None
        else None
    )


def prop(node, name, value):
    el = next(iter(descendants(node, name)), None) if node is not None else None
    return el.get(value) if el is not None else None


def category(rule):
    if any(word in rule for word in ["image", "object-alt", "visual", "alt-text"]):
        return "images"
    if "language" in rule:
        return "language"
    if any(word in rule for word in ["title", "filename", "metadata"]):
        return "metadata"
    if "contrast" in rule:
        return "contrast"
    if "link" in rule:
        return "links"
    if "media" in rule:
        return "media"
    if any(word in rule for word in ["order", "floating", "text-box"]):
        return "order"
    return "structure"


class OfficeEngine:
    def inspect(self, source: bytes, filename: str, parent_version=None):
        pkg = Package(source)
        version = DocumentVersion.from_bytes(
            source, filename, pkg.format, parent_version
        ).to_dict()
        report = {
            "schema_version": SCHEMA_VERSION,
            "engine_version": ENGINE_VERSION,
            "version": version,
            "format": pkg.format,
            "findings": [],
            "objects": [],
            "coverage": [],
            "external_validation": [],
            "reader_tests": [],
            "edit_policy": {
                "editable": not (pkg.signed or pkg.protected),
                "signed": pkg.signed,
                "protected": pkg.protected,
                "explanation": (
                    "Signed/protected originals are inspection-only. Create an unsigned, unprotected derivative in the native application before uploading it for repair."
                    if pkg.signed or pkg.protected
                    else "Edits create a new version; the original is retained in this browser."
                ),
            },
        }
        self.pkg, self.report, self.version = pkg, report, version
        self.objects = {}
        core = pkg.xml("docProps/core.xml")
        title = (
            "".join(core.xpath("dc:title/text()", namespaces=NS))
            if core is not None
            else ""
        )
        meta_target = (
            pkg.target("docProps/core.xml", core)
            if core is not None
            else pkg.target(pkg.main, pkg.roots[pkg.main])
        )
        self.add_object(
            "metadata", "Document title", meta_target, title, ["set_title"], value=title
        )
        if pkg.format == "docx":
            self.docx()
        else:
            self.pptx()
        for part, error in pkg.errors.items():
            self.finding(
                f"{pkg.format}.coverage.xml",
                "error",
                error,
                part=part,
                severity="error",
            )
            report["coverage"].append(
                {"part": part, "outcome": "error", "detail": error}
            )
        report["coverage"].append(
            {
                "capability": "rendered_preview",
                "outcome": "not_run",
                "detail": "This is a native semantic view, not a paginated rendering. Confirm layout and behavior in Word or PowerPoint.",
            }
        )
        report["coverage"].append(
            {
                "capability": "external_validation",
                "outcome": "not_run",
                "detail": "Run the native application Accessibility Checker and record its result against this exact version.",
            }
        )
        report["coverage"].append(
            {
                "capability": "external_relationships",
                "outcome": "needs_review" if pkg.external else "not_applicable",
                "detail": f"{len(pkg.external)} external relationships inventoried; no URLs were fetched.",
            }
        )
        report["objects"] = list(self.objects.values())
        report["summary"] = summary(report["findings"])
        report["summary"]["checks_unavailable"] += sum(
            c["outcome"] in {"not_run", "unsupported", "error"}
            for c in report["coverage"]
        )
        return report

    def add_object(self, kind, label, target, content="", operations=None, **extra):
        if len(self.objects) >= 5000:
            raise PackageError(
                "This document exceeds the 5,000-object interactive review budget. Split it into smaller documents in the native application."
            )
        oid = digest((target["part"] + target["element_path"] + kind).encode())[:20]
        obj = {
            "id": oid,
            "kind": kind,
            "label": label,
            "target": target,
            "text": content[:12000],
            "operations": operations or [],
            **extra,
        }
        self.objects[oid] = obj
        return obj

    def finding(
        self,
        rule,
        outcome,
        message,
        obj=None,
        part=None,
        severity="warning",
        source_code=None,
        evidence=None,
    ):
        ref = RULE_REFERENCES.get(category(rule))
        row = {
            "id": digest((rule + str(obj["id"] if obj else part) + message).encode())[
                :24
            ],
            "rule_id": rule,
            "source_code": source_code,
            "severity": severity,
            "outcome": outcome,
            "document_version": self.version["id"],
            "source_sha256": self.version["sha256"],
            "engine_version": ENGINE_VERSION,
            "message": message,
            "target": obj["target"] if obj else None,
            "object_id": obj["id"] if obj else None,
            "location_label": obj["label"] if obj else part or "Document",
            "repair_options": obj["operations"] if obj else [],
            "evidence": evidence or {},
            "wcag2ict": (
                {
                    "criterion": ref[0],
                    "rationale": ref[1],
                    "relationship": "relevant guidance; not a conformance determination",
                }
                if ref
                else None
            ),
        }
        self.report["findings"].append(row)
        return row

    def image_preview(self, part, node):
        rels = self.pkg.relationships(part)
        for el in node.iter():
            rid = el.get(q("r", "embed"))
            rel = rels.get(rid)
            if rel and not rel["external"]:
                data = self.pkg.members.get(rel["part"], b"")
                mime = (
                    "image/png"
                    if data.startswith(b"\x89PNG\r\n")
                    else "image/jpeg" if data.startswith(b"\xff\xd8") else None
                )
                if mime and len(data) < 2 * 1024 * 1024:
                    return f"data:{mime};base64," + base64.b64encode(data).decode()
        return None

    def docx(self):
        pkg = self.pkg
        default = pkg.xml("word/styles.xml")
        default_lang = ""
        if default is not None:
            values = default.xpath(
                "w:docDefaults/w:rPrDefault/w:rPr/w:lang/@w:val", namespaces=NS
            )
            default_lang = values[0] if values else ""
        self.add_object(
            "language",
            "Default document language",
            (
                pkg.target("word/styles.xml", default)
                if default is not None
                else pkg.target(pkg.main, pkg.roots[pkg.main])
            ),
            default_lang,
            ["set_default_language"],
            value=default_lang,
        )
        targets = {}
        for part in sorted(pkg.members, key=lambda p: (p != "word/document.xml", p)):
            if not re.match(
                r"^word/(document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml$",
                part,
            ):
                continue
            root = pkg.xml(part)
            if root is None:
                continue
            for index, el in enumerate(root.iter()):
                kind = local(el)
                target = pkg.target(part, el)
                label = f"{PurePosixPath(part).stem} · {kind} {index + 1}"
                if kind in {"p", "tbl", "hyperlink"} and text(el).strip():
                    label += " — " + " ".join(text(el).split())[:65]
                obj = None
                if el.tag == q("w", "p"):
                    style = prop(child(el, "pPr"), "pStyle", q("w", "val")) or ""
                    obj = self.add_object(
                        "paragraph",
                        label,
                        target,
                        text(el),
                        ["set_paragraph_role", "set_text_language"],
                        role=paragraph_role(el, pkg.xml("word/styles.xml")),
                        style=style,
                    )
                elif kind in {"drawing", "pict", "object"}:
                    nv = next(iter(descendants(el, "docPr")), None)
                    supported = nv is not None
                    if nv is not None:
                        target["object_id"] = nv.get("id")
                    alt = (
                        (nv.get("descr") or nv.get("title") or "")
                        if nv is not None
                        else ""
                    )
                    decorative = any(
                        local(n) == "decorative" and on(n.get("val")) for n in el.iter()
                    )
                    obj = self.add_object(
                        "image",
                        label,
                        target,
                        alt,
                        (
                            ["set_alt_text", "mark_decorative", "mark_informative"]
                            if supported
                            else []
                        ),
                        value=alt,
                        decorative=decorative,
                        preview=self.image_preview(part, el),
                    )
                    if not supported:
                        self.finding(
                            "docx.visual.unsupported",
                            "unsupported",
                            "This legacy/embedded object needs review in Word; its native representation is preserved.",
                            obj,
                        )
                elif kind == "tbl":
                    rows = [n for n in el if local(n) == "tr"]
                    complex_table = any(
                        local(n) in {"gridSpan", "vMerge"}
                        or (local(n) == "tbl" and n is not el)
                        for n in el.iter()
                    )
                    header_node = (
                        next(iter(descendants(rows[0], "tblHeader")), None)
                        if rows
                        else None
                    )
                    is_header = header_node is not None and on(
                        header_node.get(q("w", "val"))
                    )
                    obj = self.add_object(
                        "table",
                        label,
                        target,
                        text(el),
                        ["set_table_title"] + (["set_table_header"] if rows and not complex_table else []),
                        table_title=prop(child(el, "tblPr"), "tblCaption", q("w", "val")) or "",
                        rows=[
                            [text(cell) for cell in row if local(cell) == "tc"]
                            for row in rows
                        ],
                        header=is_header,
                        complex=complex_table,
                    )
                elif kind == "hyperlink":
                    runs = [n for n in el if local(n) == "r"]
                    simple = (
                        len(runs) == 1
                        and len(descendants(el, "t")) == 1
                        and not any(
                            local(n) in {"fldChar", "instrText", "drawing"}
                            for n in el.iter()
                        )
                    )
                    obj = self.add_object(
                        "link",
                        label,
                        target,
                        text(el),
                        [],
                        value=text(el),
                        destination=pkg.relationships(part)
                        .get(el.get(q("r", "id")), {})
                        .get("target", el.get(q("w", "anchor"), "")),
                    )
                    if not simple:
                        self.finding(
                            "docx.link.complex",
                            "needs_review",
                            "Edit this multi-run or field-based link in Word; its structure is preserved.",
                            obj,
                        )
                if obj:
                    targets[(part, target["element_path"])] = obj
        with tempfile.TemporaryDirectory(prefix="office-scan-") as folder:
            path = PurePosixPath(folder) / "input.docx"
            from pathlib import Path

            Path(path).write_bytes(pkg.data)
            raw = check_docx_accessibility(
                path,
                DocxAccessibilityOptions(max_severity=Severity.ERROR),
                logical_filename=self.version["filename"],
            )
            raw += check_docx_review_markup(path)
        found_codes = set()
        for finding in raw:
            found_codes.add(finding.code)
            context = dict(finding.context)
            part = str(context.get("part", "Document"))
            obj = targets.get((part, context.get("element_path")))
            if finding.code == "IA561":
                obj = next(o for o in self.objects.values() if o["kind"] == "metadata")
            if finding.code == "EA545":
                obj = next(o for o in self.objects.values() if o["kind"] == "language")
            rule = "docx." + DOCX_RULES.get(finding.code, "review-markup").replace(
                "-", "."
            )
            outcome = (
                "error"
                if finding.code == "EA540"
                else (
                    "fail"
                    if finding.code in {"EA541", "EA542", "EA543", "EA544", "EA545"}
                    else "needs_review"
                )
            )
            self.finding(
                rule,
                outcome,
                finding.message,
                obj,
                part,
                severity=str(finding.severity),
                source_code=finding.code,
                evidence={
                    "context": context,
                    "upstream_message_id": finding.message_id,
                    "rule_scope": "implemented checker heuristic; no full WCAG conformance claim",
                },
            )
        self.report["rule_inventory"] = [
            {
                "source_code": code,
                "rule_id": "docx." + name.replace("-", "."),
                "detector_result": "reported" if code in found_codes else "no_finding",
                "detail": "No finding means this implemented detector did not report a condition; it is not proof of accessibility.",
            }
            for code, name in DOCX_RULES.items()
        ]
        self.finding(
            "docx.reading.order",
            "needs_review",
            "Review the semantic sequence, floating objects, and headers/footers in Word with a screen reader.",
        )
        self.report["coverage"].append(
            {
                "capability": "docx-effective-formatting",
                "outcome": "unsupported",
                "detail": "Contrast and style heuristics cover a subset of effective formatting. Theme/background and layout-dependent cases require Word review.",
            }
        )

    def pptx(self):
        pkg = self.pkg
        main = pkg.roots[pkg.main]
        rels = pkg.relationships(pkg.main)
        slide_ids = main.xpath("p:sldIdLst/p:sldId", namespaces=NS)
        titles = []
        self.add_object(
            "language",
            "Presentation default language",
            pkg.target(pkg.main, main),
            "",
            ["set_default_language"],
            value="",
        )
        meta = next(o for o in self.objects.values() if o["kind"] == "metadata")
        self.finding(
            "pptx.document.metadata",
            "needs_review" if not meta["text"].strip() else "pass",
            "Confirm a descriptive document title.",
            meta,
        )
        for number, slide_id in enumerate(slide_ids, 1):
            rel = rels.get(slide_id.get(q("r", "id")))
            if not rel or rel["external"] or rel["part"] not in pkg.members:
                raise PackageError(
                    f"Slide {number} has a broken required relationship."
                )
            part = rel["part"]
            root = pkg.xml(part, required=True)
            related = pkg.relationships(part)
            layout_rel = next(
                (
                    r
                    for r in related.values()
                    if r["type"].endswith("/slideLayout") and not r["external"]
                ),
                None,
            )
            layout = pkg.xml(layout_rel["part"]) if layout_rel else None
            layout_rels = pkg.relationships(layout_rel["part"]) if layout_rel else {}
            master_rel = next(
                (
                    r
                    for r in layout_rels.values()
                    if r["type"].endswith("/slideMaster") and not r["external"]
                ),
                None,
            )
            master = pkg.xml(master_rel["part"]) if master_rel else None
            chain = [root, layout, master]
            title_objects = []
            shape_count = 0
            complex_count = 0
            media_count = 0
            tree = root.find("p:cSld/p:spTree", NS)
            if tree is None:
                raise PackageError(f"Slide {number} has no shape tree.")
            slide = self.add_object(
                "slide", f"Slide {number}", pkg.target(part, root), "", [], slide=number
            )
            for el in tree.iter():
                if local(el) not in {"sp", "pic", "graphicFrame", "grpSp", "cxnSp"}:
                    continue
                shape_count += 1
                nv = next(iter(descendants(el, "cNvPr")), None)
                shape_id = nv.get("id", "") if nv is not None else ""
                label = f'Slide {number} · {nv.get("name", "Shape") if nv is not None else "Shape"} ({shape_id})'
                target = pkg.target(part, el)
                target["object_id"] = shape_id
                target["slide_id"] = slide_id.get("id")
                nonvisual = next((n for n in el if local(n).startswith("nv")), None)
                ph = (
                    next(iter(descendants(nonvisual, "ph")), None)
                    if nonvisual is not None
                    else None
                )
                ph_type = ph.get("type", "") if ph is not None else ""
                inherited = []
                if ph is not None:
                    for ancestor in [layout, master]:
                        if ancestor is None:
                            continue
                        match = next(
                            (
                                node
                                for node in descendants(ancestor, "sp")
                                if any(
                                    p.get("idx", "0") == ph.get("idx", "0")
                                    for p in descendants(node, "ph")
                                )
                            ),
                            None,
                        )
                        if match is not None:
                            inherited.append(match)
                            if not ph_type:
                                ph_type = next(iter(descendants(match, "ph"))).get(
                                    "type", ""
                                )
                is_title = ph_type in {"title", "ctrTitle"}
                tables = descendants(el, "tbl")
                visual = local(el) in {"pic", "grpSp"} or bool(
                    descendants(el, "chart") or descendants(el, "relIds")
                )
                alt = (
                    (nv.get("descr") or nv.get("title") or "") if nv is not None else ""
                )
                decorative = any(
                    local(n) == "decorative" and on(n.get("val"))
                    for n in (nv.iter() if nv is not None else [])
                )
                content = text(el)
                operations = []
                kind = (
                    "title"
                    if is_title
                    else "table" if tables else "image" if visual else "shape"
                )
                if visual and nv is not None:
                    operations += [
                        "set_alt_text",
                        "mark_decorative",
                        "mark_informative",
                    ]
                text_nodes = descendants(el, "t")
                if is_title and len(text_nodes) <= 1 and not descendants(el, "fld"):
                    operations.append("set_existing_title")
                if content.strip():
                    operations.append("set_text_language")
                table = tables[0] if tables else None
                complex_table = bool(
                    table is not None
                    and any(
                        local(n) in {"tc"}
                        and (
                            n.get("gridSpan", "1") != "1"
                            or n.get("rowSpan", "1") != "1"
                            or n.get("hMerge") in {"1", "true"}
                            or n.get("vMerge") in {"1", "true"}
                        )
                        for n in table.iter()
                    )
                )
                if table is not None and not complex_table:
                    operations.append("set_table_header")
                obj = self.add_object(
                    kind,
                    label,
                    target,
                    content,
                    operations,
                    slide=number,
                    value=alt if visual else content,
                    decorative=decorative,
                    preview=self.image_preview(part, el),
                    shape_id=shape_id,
                    rows=(
                        [
                            [text(c) for c in row if local(c) == "tc"]
                            for row in table
                            if local(row) == "tr"
                        ]
                        if table is not None
                        else None
                    ),
                    header=(
                        on(child(table, "tblPr").get("firstRow", "0"))
                        if table is not None and child(table, "tblPr") is not None
                        else False
                    ),
                )
                if is_title:
                    title_objects.append(obj)
                    titles.append((content.strip().casefold(), obj))
                    self.finding(
                        "pptx.slide.title",
                        "pass" if content.strip() else "fail",
                        (
                            "Native title placeholder is present."
                            if content.strip()
                            else "The native title placeholder is empty."
                        ),
                        obj,
                        severity="error",
                    )
                if visual:
                    self.finding(
                        "pptx.visual.alternative",
                        "pass" if decorative or alt.strip() else "fail",
                        (
                            "Review the description in context."
                            if alt.strip()
                            else "This visual needs a description or an explicit decorative decision."
                        ),
                        obj,
                        severity="error",
                    )
                    self.finding(
                        "pptx.visual.decorative",
                        "needs_review" if decorative and alt.strip() else "pass",
                        (
                            "Decorative and informative alternatives conflict."
                            if decorative and alt.strip()
                            else "Review whether this visual conveys information."
                        ),
                        obj,
                    )
                if table is not None:
                    self.finding(
                        "pptx.table.structure",
                        "needs_review",
                        "Review table meaning and header cells. First-row formatting does not prove screen-reader header semantics."
                        + (
                            " Merged cells need review in PowerPoint."
                            if complex_table
                            else ""
                        ),
                        obj,
                    )
                if content.strip():
                    self.pptx_text(obj, el, inherited, master, main, ph_type)
                for link in descendants(el, "hlinkClick"):
                    tip = link.get("tooltip", "")
                    run = link.getparent()
                    label_text = (
                        text(run.getparent())
                        if run is not None and local(run) == "rPr"
                        else content
                    )
                    self.finding(
                        "pptx.link.purpose",
                        (
                            "needs_review"
                            if label_text.strip().lower()
                            in {"", "here", "click here", "link"}
                            else "pass"
                        ),
                        "Check the link purpose and destination in PowerPoint. Destination is preserved.",
                        obj,
                        evidence={
                            "visible_text": label_text,
                            "screen_tip": tip,
                            "target": related.get(link.get(q("r", "id")), {}).get(
                                "target"
                            ),
                        },
                    )
                media = [
                    n
                    for n in el.iter()
                    if local(n) in {"videoFile", "audioFile", "media", "wavAudioFile"}
                ]
                if media:
                    media_count += len(media)
                    tracks = [
                        r["part"]
                        for r in related.values()
                        if "track" in r["type"].lower() or r["part"].endswith(".vtt")
                    ]
                    self.finding(
                        "pptx.media.alternatives",
                        "needs_review",
                        "Review captions, timing, audio description, and whether the media is silent. Attached tracks alone do not establish accessibility.",
                        obj,
                        evidence={"attached_tracks": tracks, "media_items": len(media)},
                    )
                if (
                    descendants(el, "relIds")
                    or descendants(el, "oleObj")
                    or local(el) == "grpSp"
                ):
                    complex_count += 1
                    self.finding(
                        "pptx.complex_content",
                        "unsupported",
                        "SmartArt, embedded objects, and groups are preserved. Review their semantics and behavior in PowerPoint.",
                        obj,
                    )
            if not title_objects:
                self.finding(
                    "pptx.slide.title",
                    "fail",
                    "No native title placeholder is present. Add one in PowerPoint; an ordinary text box or shape name is not a native title.",
                    slide,
                    severity="error",
                )
            if descendants(root, "timing"):
                complex_count += 1
                self.finding(
                    "pptx.complex_content",
                    "unsupported",
                    "Animation timing is preserved and requires review in PowerPoint.",
                    slide,
                )
            self.finding(
                "pptx.reading_order",
                "needs_review",
                "Review the shape sequence in PowerPoint’s Reading Order pane. Reordering can change stacking and animation behavior; in-app reordering is not enabled.",
                slide,
                evidence={"shape_count": shape_count},
            )
            self.finding(
                "pptx.color.meaning",
                "needs_review",
                "Check that color is not the only way to communicate meaning.",
                slide,
            )
            if not media_count:
                self.finding(
                    "pptx.media.alternatives",
                    "not_applicable",
                    "No media elements detected on this slide.",
                    slide,
                )
            if not complex_count:
                self.finding(
                    "pptx.complex_content",
                    "pass",
                    "No SmartArt, embedded objects or groups detected by this scan.",
                    slide,
                )
            if not any(
                o["kind"] == "table" and o.get("slide") == number
                for o in self.objects.values()
            ):
                self.finding(
                    "pptx.table.structure",
                    "not_applicable",
                    "No tables detected on this slide.",
                    slide,
                )
            if not descendants(root, "hlinkClick"):
                self.finding(
                    "pptx.link.purpose",
                    "not_applicable",
                    "No click hyperlinks detected on this slide.",
                    slide,
                )
            if not any(
                o["kind"] == "image" and o.get("slide") == number
                for o in self.objects.values()
            ):
                for family in ["pptx.visual.alternative", "pptx.visual.decorative"]:
                    self.finding(
                        family,
                        "not_applicable",
                        "No standalone visual alternatives detected on this slide.",
                        slide,
                    )
            self.report["coverage"].append(
                {
                    "part": part,
                    "outcome": "needs_review",
                    "detail": "Slide content inventoried; inherited/master visual content and notes require native-application review.",
                }
            )
        counts = Counter(t for t, _ in titles if t)
        for title, obj in titles:
            if title and counts[title] > 1:
                self.finding(
                    "pptx.slide.title.duplicate",
                    "needs_review",
                    "This title is repeated. Confirm it distinguishes the slide in context.",
                    obj,
                )
        for name in pkg.members:
            if any(
                fragment in name
                for fragment in [
                    "/notesSlides/",
                    "/slideMasters/",
                    "/slideLayouts/",
                    "/theme/",
                ]
            ) and name.endswith(".xml"):
                self.report["coverage"].append(
                    {
                        "part": name,
                        "outcome": "needs_review",
                        "detail": "Preserved and parsed for inventory/inheritance where supported; full semantics require PowerPoint review.",
                    }
                )

    def pptx_text(self, obj, shape, inherited, master, presentation, ph_type):
        def level_defaults(node, level):
            result = []
            if node is None:
                return result
            for listing in descendants(node, "lstStyle"):
                for name in [f"lvl{level+1}pPr", "defPPr"]:
                    props = child(child(listing, name), "defRPr")
                    if props is not None:
                        result.append(props)
            return result

        languages = []
        sizes = []
        unresolved_language = False
        unresolved_size = False
        for run in descendants(shape, "r") + descendants(shape, "fld"):
            if not text(run).strip():
                continue
            own = child(run, "rPr")
            paragraph = run.getparent()
            paragraph_default = child(child(paragraph, "pPr"), "defRPr")
            ppr = child(paragraph, "pPr")
            try:
                level = int(ppr.get("lvl", "0")) if ppr is not None else 0
            except ValueError:
                level = 0
            defaults = level_defaults(shape, level)
            for ancestor in inherited:
                defaults += level_defaults(ancestor, level)
                for para in descendants(ancestor, "p"):
                    props = child(para, "pPr")
                    if props is not None and props.get("lvl", "0") == str(level):
                        rpr = child(props, "defRPr")
                        if rpr is not None:
                            defaults.append(rpr)
            style = (
                "titleStyle"
                if ph_type in {"title", "ctrTitle"}
                else "bodyStyle" if ph_type == "body" else "otherStyle"
            )
            for parent in (
                [n for n in descendants(master, style)] if master is not None else []
            ) + descendants(presentation, "defaultTextStyle"):
                for name in [f"lvl{level+1}pPr", "defPPr"]:
                    props = child(child(parent, name), "defRPr")
                    if props is not None:
                        defaults.append(props)
            candidates = [
                n for n in [own, paragraph_default] + defaults if n is not None
            ]
            lang = next((n.get("lang") for n in candidates if n.get("lang")), None)
            size = next((n.get("sz") for n in candidates if n.get("sz")), None)
            if lang:
                languages.append(lang)
            else:
                unresolved_language = True
            if size:
                try:
                    sizes.append(int(size) / 100)
                except ValueError:
                    unresolved_size = True
            else:
                unresolved_size = True
        obj["languages"] = sorted(set(languages))
        obj["font_sizes"] = sorted(set(sizes))
        self.finding(
            "pptx.text.language",
            "needs_review" if unresolved_language or not languages else "pass",
            (
                "Effective language could not be resolved for all text; confirm it in PowerPoint or set the selected text language."
                if unresolved_language or not languages
                else "Language resolved from text and applicable defaults."
            ),
            obj,
            evidence={"languages": obj["languages"]},
        )
        self.finding(
            "pptx.text.readability",
            (
                "needs_review"
                if unresolved_size
                or not sizes
                or any(s < 18 for s in sizes)
                or len(text(shape)) > 700
                else "pass"
            ),
            "Review type size and text density for the audience. The 18-point/700-character thresholds are advice, not WCAG failures.",
            obj,
            evidence={
                "resolved_sizes": sizes,
                "unresolved_font_size": unresolved_size or not sizes,
                "text_length": len(text(shape)),
            },
        )
        self.finding(
            "pptx.text.contrast",
            "needs_review",
            "Effective backgrounds, theme transformations, transparency, and overlaps are not fully resolved. Check contrast in the rendered slide; no white background is assumed.",
            obj,
        )
