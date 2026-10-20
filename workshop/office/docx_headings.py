"""Paragraph roles using python-docx properties, without resaving the package."""

from copy import deepcopy
from lxml import etree as ET
from docx.oxml import parse_xml
from docx.enum.style import WD_STYLE_TYPE
from docx.styles.styles import Styles
from .package import q, NS

ROLES = {
    "body": "Normal",
    "title": "Title",
    **{f"heading{i}": f"Heading {i}" for i in range(1, 10)},
}


def paragraph_role(node, styles):
    properties = node.find(q("w", "pPr"))
    style_node = properties.find(q("w", "pStyle")) if properties is not None else None
    style_id = style_node.get(q("w", "val"), "") if style_node is not None else ""
    definitions = {
        s.get(q("w", "styleId")): s
        for s in (styles if styles is not None else [])
        if s.tag == q("w", "style")
    }
    seen = set()
    current = definitions.get(style_id)
    candidates = [properties]
    title = style_id.lower() == "title"
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = current.find(q("w", "name"))
        title |= name is not None and name.get(q("w", "val"), "").lower() == "title"
        candidates.append(current.find(q("w", "pPr")))
        based = current.find(q("w", "basedOn"))
        current = (
            definitions.get(based.get(q("w", "val"))) if based is not None else None
        )
    for props in candidates:
        outline = props.find(q("w", "outlineLvl")) if props is not None else None
        if outline is not None:
            value = outline.get(q("w", "val"), "")
            if value in [str(i) for i in range(9)]:
                return f"heading{int(value) + 1}"
            return "title" if title else "body"
    return "title" if title else "body"


def apply_role(pkg, node, role):
    from .repairs import add_part

    original_styles = pkg.xml("word/styles.xml")
    if original_styles is None:
        original_styles = ET.Element(q("w", "styles"), nsmap={"w": NS["w"]})
        add_part(
            pkg,
            "word/styles.xml",
            original_styles,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
            "word/document.xml",
            NS["r"] + "/styles",
        )
    styles = Styles(parse_xml(ET.tostring(original_styles)))
    name = ROLES[role]
    style = next(
        (s for s in styles if s.type == WD_STYLE_TYPE.PARAGRAPH and s.name == name),
        None,
    )
    if style is None:
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH, builtin=True)
        # Do not collide with unusual existing style IDs.
        reserved = {s.get(q("w", "styleId")) for s in original_styles}
        candidate = style.style_id
        suffix = 1
        while candidate in reserved:
            candidate = f"Workshop{role}{suffix}"
            suffix += 1
        style.style_id = candidate
        style.quick_style = True
        original_styles.append(deepcopy(style.element))
        pkg.touch("word/styles.xml")
    paragraph = parse_xml(ET.tostring(node))
    props = paragraph.get_or_add_pPr()
    props.style = style.style_id
    props.get_or_add_outlineLvl().val = (
        int(role[7:]) - 1 if role.startswith("heading") else 9
    )
    old = node.find(q("w", "pPr"))
    if old is not None:
        node.replace(old, deepcopy(props))
    else:
        node.insert(0, deepcopy(props))
