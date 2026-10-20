"""Digest-bound, allow-listed edits with per-member preservation receipts."""

import json
import re
from lxml import etree as ET
from workshop.contracts import ENGINE_VERSION, DocumentVersion, digest
from .package import Package, PackageError, Conflict, NS, q, local, descendants
from .engine import OfficeEngine, child


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def plan_repairs(source, filename, expected_sha256, decisions, idempotency_key):
    if digest(source) != expected_sha256:
        raise Conflict(
            "This plan targets an older document version. Inspect the current file again."
        )
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= 30:
        raise PackageError("Supply between 1 and 30 explicit repair decisions.")
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
        raise PackageError("An idempotency key of 8–128 characters is required.")
    report = OfficeEngine().inspect(source, filename)
    if not report["edit_policy"]["editable"]:
        raise PackageError(report["edit_policy"]["explanation"])
    if any(c["outcome"] == "error" for c in report["coverage"]):
        raise PackageError(
            "Repair is disabled while package parsing or relationships are incomplete. Fix the package in its native application first."
        )
    objects = {o["id"]: o for o in report["objects"]}
    operations = []
    for decision in decisions:
        if not isinstance(decision, dict):
            raise PackageError("Each decision must be an object.")
        obj = objects.get(decision.get("object_id"))
        action = decision.get("action")
        if not obj or action not in obj["operations"]:
            raise PackageError(
                "This operation is not supported for the selected native object."
            )
        value = decision.get("value", "")
        merge_targets = None
        if action == "merge_paragraphs":
            from .merge import validate_merge
            if len(decisions) != 1 or not isinstance(value, list) or any(not isinstance(i, str) or i not in objects for i in value):
                raise PackageError("Submit one merge with a list of selected paragraph IDs.")
            if not value or value[0] != obj['id']:
                raise PackageError("The merge must target its first paragraph.")
            selected = [objects[i] for i in value]
            validate_merge(Package(source), selected)
            merge_targets = [o['target'] for o in selected]
        elif action in {"set_default_language", "set_text_language"}:
            if not isinstance(value, str) or not re.fullmatch(
                r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value
            ):
                raise PackageError("Enter a BCP 47 language tag, such as en-US or es.")
        elif action == "set_paragraph_role":
            from .docx_headings import ROLES
            if not isinstance(value, str) or value not in ROLES:
                raise PackageError("Choose Body text, Title, or Heading 1–9.")
        elif action == "set_table_header":
            if value is not True:
                raise PackageError(
                    "Confirm that this is a simple data table with a meaningful first header row."
                )
        elif action not in {"mark_decorative", "mark_informative"}:
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise PackageError(
                    "Enter a nonempty value of at most 4,000 characters."
                )
        operations.append(
            {
                "action": action,
                "value": value,
                "target": obj["target"],
                "object_id": obj["id"],
                "label": obj["label"],
                **({"merge_targets": merge_targets} if merge_targets else {}),
            }
        )
    body = {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "source_sha256": expected_sha256,
        "source_version": report["version"]["id"],
        "filename": filename,
        "format": report["format"],
        "operations": operations,
        "idempotency_key": idempotency_key,
    }
    body["id"] = digest(canonical(body))
    return body


def ensure(parent, tag, first=False):
    node = parent.find(tag)
    if node is None:
        node = ET.Element(tag)
        if first:
            parent.insert(0, node)
        else:
            parent.append(node)
    return node


def add_part(pkg, name, root, ctype, owner, reltype):
    pkg.roots[name] = root
    pkg.touch(name)
    types = pkg.roots["[Content_Types].xml"]
    if not any(el.get("PartName") == "/" + name for el in types):
        ET.SubElement(
            types, q("ct", "Override"), PartName="/" + name, ContentType=ctype
        )
        pkg.touch("[Content_Types].xml")
    from posixpath import dirname, basename, join, relpath

    relname = (
        join(dirname(owner), "_rels", basename(owner) + ".rels")
        if owner
        else "_rels/.rels"
    )
    relroot = pkg.xml(relname)
    if relroot is None:
        relroot = ET.Element(q("rel", "Relationships"), nsmap={None: NS["rel"]})
        pkg.roots[relname] = relroot
    ids = {el.get("Id") for el in relroot}
    index = 1
    while f"rIdA11y{index}" in ids:
        index += 1
    ET.SubElement(
        relroot,
        q("rel", "Relationship"),
        Id=f"rIdA11y{index}",
        Type=reltype,
        Target=relpath(name, dirname(owner)) if owner else name,
    )
    pkg.touch(relname)


def alt_node(pkg, node):
    names = ["docPr"] if pkg.format == "docx" else ["cNvPr"]
    return next((el for el in node.iter() if local(el) in names), None)


def decorative(nv, value):
    marker = next(
        (
            el
            for el in nv.iter()
            if local(el) == "decorative" and ET.QName(el).namespace == NS["adec"]
        ),
        None,
    )
    if marker is None:
        extensions = ensure(nv, q("a", "extLst"))
        extension = ET.SubElement(
            extensions, q("a", "ext"), uri="{C183D7F6-B498-43B3-948B-1728B52AA6E4}"
        )
        marker = ET.SubElement(
            extension, q("adec", "decorative"), nsmap={"adec": NS["adec"]}
        )
    marker.set("val", "1" if value else "0")


def apply_operation(pkg, op, node):
    action = op["action"]
    value = op["value"]
    part = op["target"]["part"]
    if action == "set_title":
        core = pkg.xml("docProps/core.xml")
        if core is None:
            core = ET.Element(
                q("cp", "coreProperties"), nsmap={"cp": NS["cp"], "dc": NS["dc"]}
            )
            add_part(
                pkg,
                "docProps/core.xml",
                core,
                "application/vnd.openxmlformats-package.core-properties+xml",
                "",
                NS["rel"] + "/metadata/core-properties",
            )
        ensure(core, q("dc", "title")).text = value
        pkg.touch("docProps/core.xml")
        return
    if action == "set_default_language":
        if pkg.format == "docx":
            styles = pkg.xml("word/styles.xml")
            if styles is None:
                styles = ET.Element(q("w", "styles"), nsmap={"w": NS["w"]})
                add_part(
                    pkg,
                    "word/styles.xml",
                    styles,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
                    "word/document.xml",
                    NS["r"] + "/styles",
                )
            defaults = ensure(styles, q("w", "docDefaults"), first=True)
            props = ensure(
                ensure(defaults, q("w", "rPrDefault"), first=True), q("w", "rPr")
            )
            ensure(props, q("w", "lang")).set(q("w", "val"), value)
            pkg.touch("word/styles.xml")
        else:
            presentation = pkg.roots[pkg.main]
            defaults = ensure(presentation, q("p", "defaultTextStyle"))
            extension = child(presentation, "extLst")
            if extension is not None and list(presentation).index(defaults) > list(
                presentation
            ).index(extension):
                presentation.remove(defaults)
                presentation.insert(list(presentation).index(extension), defaults)
            for name in ["defPPr"] + [f"lvl{i}pPr" for i in range(1, 10)]:
                ensure(ensure(defaults, q("a", name)), q("a", "defRPr")).set(
                    "lang", value
                )
            order = {
                q("a", name): index
                for index, name in enumerate(
                    ["defPPr"] + [f"lvl{i}pPr" for i in range(1, 10)] + ["extLst"]
                )
            }
            defaults[:] = sorted(defaults, key=lambda node: order.get(node.tag, 99))
            pkg.touch(pkg.main)
        return
    if action == "set_paragraph_role":
        from .docx_headings import apply_role
        apply_role(pkg, node, value)
    elif action == "set_text_language":
        prefix = "w" if pkg.format == "docx" else "a"
        for run in list(node.iter(q(prefix, "r"))) + (
            list(node.iter(q("a", "fld"))) if prefix == "a" else []
        ):
            props = ensure(run, q(prefix, "rPr"), first=True)
            if prefix == "w":
                ensure(props, q("w", "lang")).set(q("w", "val"), value)
            else:
                props.set("lang", value)
    elif action in {"set_alt_text", "mark_decorative", "mark_informative"}:
        nv = alt_node(pkg, node)
        if nv is None:
            raise PackageError("This visual has no supported nonvisual properties.")
        if action == "set_alt_text":
            nv.set("descr", value)
            decorative(nv, False)
        elif action == "mark_decorative":
            nv.attrib.pop("descr", None)
            nv.attrib.pop("title", None)
            decorative(nv, True)
        else:
            decorative(nv, False)
    elif action == "set_table_title" and pkg.format == "pptx":
        nv = alt_node(pkg, node)
        if nv is None:
            raise PackageError("This table has no supported nonvisual properties.")
        nv.set("title", value)
    elif action == "set_table_title":
        props = ensure(node, q("w", "tblPr"), first=True)
        caption = props.find(q("w", "tblCaption"))
        if caption is None:
            caption = ET.Element(q("w", "tblCaption"))
            following = next((n for n in props if n.tag in {q("w", "tblDescription"), q("w", "tblPrChange")}), None)
            if following is None:
                props.append(caption)
            else:
                props.insert(list(props).index(following), caption)
        caption.set(q("w", "val"), value)
    elif action == "set_table_header":
        if pkg.format == "docx":
            row = next(el for el in node if local(el) == "tr")
            ensure(ensure(row, q("w", "trPr"), first=True), q("w", "tblHeader")).set(
                q("w", "val"), "1"
            )
        else:
            table = next(iter(descendants(node, "tbl")))
            ensure(table, q("a", "tblPr"), first=True).set("firstRow", "1")
    elif action in {"set_link_text", "set_existing_title"}:
        nodes = descendants(node, "t")
        if len(nodes) == 1:
            nodes[0].text = value
        elif not nodes and action == "set_existing_title":
            body = child(node, "txBody")
            if body is None:
                raise PackageError("The existing title has no text body.")
            paragraph = ensure(body, q("a", "p"))
            run = ET.Element(q("a", "r"))
            ET.SubElement(run, q("a", "t")).text = value
            last = child(paragraph, "endParaRPr")
            if last is not None:
                paragraph.insert(list(paragraph).index(last), run)
            else:
                paragraph.append(run)
        else:
            raise PackageError(
                "Text edit would replace complex content; use the native application."
            )
    else:
        raise PackageError("Unsupported repair action.")
    pkg.touch(part)


def apply_repairs(source, plan):
    if not isinstance(plan, dict) or digest(source) != plan.get("source_sha256"):
        raise Conflict(
            "The repair plan targets a different version. No changes were made."
        )
    # Rebuild the allow-list from this source; a client cannot invent a target/action.
    if not isinstance(plan.get("operations"), list) or any(
        not isinstance(op, dict) for op in plan["operations"]
    ):
        raise PackageError("Plan operations must be a list of objects.")
    if not isinstance(plan.get("filename"), str) or not isinstance(
        plan.get("idempotency_key"), str
    ):
        raise PackageError("Plan filename and idempotency key are required.")
    decisions = [
        {
            "object_id": op.get("object_id"),
            "action": op.get("action"),
            "value": op.get("value"),
        }
        for op in plan.get("operations", [])
    ]
    verified = plan_repairs(
        source,
        plan["filename"],
        plan["source_sha256"],
        decisions,
        plan["idempotency_key"],
    )
    if canonical(verified) != canonical(plan):
        raise Conflict("The plan or native target changed. Request a new repair plan.")
    pkg = Package(source)
    located = [pkg.locate(op["target"]) for op in plan["operations"]]
    merged = False
    for op, node in zip(plan["operations"], located):
        if op['action'] == 'merge_paragraphs':
            from .merge import merge_nodes
            merge_nodes([pkg.locate(target) for target in op['merge_targets']])
            pkg.touch(op['target']['part'])
            merged = True
        else:
            apply_operation(pkg, op, node)
    after = pkg.write()
    reopened = Package(after)
    # A repair may add only the specifically created metadata/style parts. All
    # unrelated member payloads must match exactly, including relationships/media.
    unchanged = [name for name in pkg.members if name not in pkg.changed]
    if any(pkg.members[name] != reopened.members.get(name) for name in unchanged):
        raise PackageError(
            "Preservation verification failed; the original remains available."
        )
    # Reapply the exact semantic operations to the reopened package. A supported
    # assignment must now be a no-op at the member payload level.
    for op in plan["operations"]:
        if op["action"] != "merge_paragraphs":
            apply_operation(reopened, op, reopened.locate(op["target"], validate=False))
    reapplied = Package(reopened.write())
    if reapplied.members != Package(after).members:
        raise PackageError("Repair postcondition or idempotence verification failed.")
    inspection = OfficeEngine().inspect(
        after, plan["filename"], parent_version=plan["source_version"]
    )
    receipt = {
        "plan_id": plan["id"],
        "idempotency_key": plan["idempotency_key"],
        "source_sha256": digest(source),
        "output_sha256": digest(after),
        "source_version": plan["source_version"],
        "output_version": inspection["version"]["id"],
        "operations": plan["operations"],
        "changed_parts": sorted(pkg.changed),
        "verification": {
            "native_reopen": "pass",
            "operation_idempotence": "not_applicable" if merged else "pass",
            "merge_content_preservation": "pass" if merged else "not_applicable",
            "unchanged_member_payloads": "pass",
            "unchanged_members": len(unchanged),
            "rendered_comparison": "not_run",
            "native_application_test": "not_run",
        },
    }
    return after, inspection, receipt
