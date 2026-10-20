"""Explicit merges of adjacent ordinary paragraphs, preserving run content."""

from copy import deepcopy
from lxml import etree as ET
from .package import PackageError, q


def validate_merge(pkg, objects):
    if not 2 <= len(objects) <= 30 or len({o["id"] for o in objects}) != len(objects):
        raise PackageError("Select 2–30 distinct adjacent paragraphs to merge.")
    if (
        any(o["kind"] != "paragraph" for o in objects)
        or len({o["target"]["part"] for o in objects}) != 1
    ):
        raise PackageError("Merge only paragraphs in the same document part.")
    nodes = [pkg.locate(o["target"]) for o in objects]
    parent = nodes[0].getparent()
    if any(n.getparent() is not parent for n in nodes):
        raise PackageError(
            "Paragraphs must share one parent. Merging across table cells or other containers is unsupported."
        )
    positions = [list(parent).index(n) for n in nodes]
    if positions != list(range(positions[0], positions[0] + len(nodes))):
        raise PackageError(
            "Select adjacent paragraphs in document order, without skipping a block."
        )
    blocked = {
        "sectPr",
        "numPr",
        "pPrChange",
        "ins",
        "del",
        "moveFrom",
        "moveTo",
        "fldChar",
        "instrText",
        "bookmarkStart",
        "bookmarkEnd",
        "commentRangeStart",
        "commentRangeEnd",
        "commentReference",
        "permStart",
        "permEnd",
        "drawing",
        "pict",
        "object",
    }
    if any(
        n.tag == q("w", tag) for node in nodes for n in node.iter() for tag in blocked
    ):
        raise PackageError(
            "Merge currently supports ordinary text paragraphs. Lists, sections, revisions, fields, images and referenced ranges must remain separate."
        )
    return nodes


def merge_nodes(nodes):
    first = nodes[0]
    expected = [deepcopy(c) for c in first if c.tag != q("w", "pPr")]
    for node in nodes[1:]:
        line = ET.Element(q("w", "r"))
        ET.SubElement(line, q("w", "br"))
        first.append(line)
        expected.append(deepcopy(line))
        for child in list(node):
            if child.tag != q("w", "pPr"):
                expected.append(deepcopy(child))
                first.append(child)
        node.getparent().remove(node)
    actual = [c for c in first if c.tag != q("w", "pPr")]

    # Compare structure without differences in inherited namespace declarations.
    def identity(n):
        return (n.tag, dict(n.attrib), n.text, n.tail, [identity(c) for c in n])

    if [identity(c) for c in actual] != [identity(c) for c in expected]:
        raise PackageError("Merge preservation failed; the original remains available.")
