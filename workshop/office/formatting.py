"""Conservative native text formatting and WCAG contrast evidence.

Unknown compositing remains unknown. These results describe package properties,
not a rendered/native-application validation.
"""

import re
from lxml import etree as ET
from .package import NS, q, local, descendants, text, on


def child(node, name):
    return (
        next((n for n in node if local(n) == name), None) if node is not None else None
    )


def rgb(value):
    return (
        value.upper()
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{6}", value)
        else None
    )


def ratio(a, b):
    def luminance(color):
        values = [int(color[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        values = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values
        ]
        return sum(a * b for a, b in zip(values, (0.2126, 0.7152, 0.0722)))

    x, y = sorted([luminance(a), luminance(b)])
    return (y + 0.05) / (x + 0.05)


def theme_colors(root):
    if root is None:
        return {}
    scheme = next(iter(descendants(root, "clrScheme")), None)
    if scheme is None:
        return {}
    return {
        local(n): rgb(
            n[0].get("val") if local(n[0]) == "srgbClr" else n[0].get("lastClr")
        )
        for n in scheme
        if len(n)
    }


def color(node, theme, mapping=None, placeholder=None):
    if node is None:
        return None
    kind = local(node)
    if kind == "srgbClr":
        value = rgb(node.get("val"))
    elif kind == "sysClr":
        value = rgb(node.get("lastClr"))
    elif kind == "schemeClr":
        key = node.get("val")
        value = (
            placeholder if key == "phClr" else theme.get((mapping or {}).get(key, key))
        )
    else:
        return None
    if not value:
        return None
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    # Unsupported transforms (including alpha) must not become a solid color.
    for transform in node:
        name = local(transform)
        try:
            amount = int(transform.get("val")) / 100000
        except (ValueError, TypeError):
            return None
        if not 0 <= amount <= 1:
            return None
        if name == "tint":
            channels = [c + (1 - c) * amount for c in channels]
        elif name == "shade":
            channels = [c * amount for c in channels]
        elif name == "alpha" and amount == 1:
            pass
        else:
            return None  # luminance transforms require HSL, not RGB arithmetic
    return "".join(f"{round(max(0,min(1,c))*255):02X}" for c in channels)


def fill(parent, theme, mapping, placeholder=None):
    if parent is None:
        return False, None
    for node in parent:
        if local(node) == "solidFill":
            return True, (
                color(node[0], theme, mapping, placeholder) if len(node) == 1 else None
            )
        if local(node) in {"gradFill", "blipFill", "pattFill", "grpFill"}:
            return True, None
        if local(node) == "noFill":
            return True, None
    return False, None


def sample(content, foreground, background, size, bold):
    if size is not None and size <= 0:
        size = None
    large = size is not None and (size >= 18 or size >= 14 and bold is True)
    threshold = 3.0 if large else 4.5
    contrast = ratio(foreground, background) if foreground and background else None
    ambiguous_size = size is None or 14 <= size < 18 and bold is None
    outcome = (
        "needs_review"
        if contrast is None
        else (
            "pass"
            if contrast >= threshold
            else "needs_review" if ambiguous_size and contrast >= 3 else "fail"
        )
    )
    return {
        "text": content[:120],
        "foreground": foreground,
        "background": background,
        "font_size": size,
        "bold": bold,
        "ratio": contrast,
        "required_ratio": threshold,
        "outcome": outcome,
    }


def summarize(samples):
    failing = [s for s in samples if s["outcome"] == "fail"]
    unknown = [s for s in samples if s["outcome"] == "needs_review"]
    outcome = (
        "fail"
        if failing
        else "needs_review" if unknown else "pass" if samples else "not_applicable"
    )
    candidates = [
        c
        for c in ("000000", "FFFFFF")
        if samples
        and not unknown
        and all(ratio(c, s["background"]) >= s["required_ratio"] for s in samples)
    ]
    return {
        "outcome": outcome,
        "samples": samples[:100],
        "sample_count": len(samples),
        "failed_runs": len(failing),
        "unresolved_runs": len(unknown),
        "suggested_colors": candidates,
        "font_sizes": sorted(
            {s["font_size"] for s in samples if s["font_size"] is not None}
        ),
        "foregrounds": sorted({s["foreground"] for s in samples if s["foreground"]}),
        "scope": "Native text properties; confirm appearance and clipping in the native application.",
    }


def docx_samples(pkg, paragraph):
    styles = pkg.xml("word/styles.xml")
    by_id = {
        s.get(q("w", "styleId")): s
        for s in (styles if styles is not None else [])
        if local(s) == "style"
    }

    def chain(style_id):
        result, seen = [], set()
        while style_id in by_id and style_id not in seen:
            seen.add(style_id)
            style = by_id[style_id]
            result.append(style)
            base = child(style, "basedOn")
            style_id = base.get(q("w", "val")) if base is not None else None
        return result

    ppr = child(paragraph, "pPr")
    pstyle = child(ppr, "pStyle")
    default_style = next(
        (
            s.get(q("w", "styleId"))
            for s in by_id.values()
            if s.get(q("w", "type")) == "paragraph"
            and on(s.get(q("w", "default"), "0"))
        ),
        None,
    )
    pchain = chain(pstyle.get(q("w", "val")) if pstyle is not None else default_style)
    defaults = child(child(child(styles, "docDefaults"), "rPrDefault"), "rPr")
    theme_rel = next(
        (
            r
            for r in pkg.relationships(pkg.main).values()
            if r["type"].endswith("/theme") and not r["external"]
        ),
        None,
    )
    theme = theme_colors(pkg.xml(theme_rel["part"])) if theme_rel else {}
    mapping = child(pkg.xml("word/settings.xml"), "clrSchemeMapping")
    defaults_map = {
        "bg1": "light1",
        "t1": "dark1",
        "bg2": "light2",
        "t2": "dark2",
        "hyperlink": "hyperlink",
        "followedHyperlink": "followedHyperlink",
        **{f"accent{i}": f"accent{i}" for i in range(1, 7)},
    }
    if mapping is not None and any(
        value != defaults_map.get(ET.QName(key).localname, value)
        for key, value in mapping.attrib.items()
    ):
        theme = {}  # Custom theme remapping needs native-application review.
    aliases = {
        "dark1": "dk1",
        "light1": "lt1",
        "dark2": "dk2",
        "light2": "lt2",
        "hyperlink": "hlink",
        "followedHyperlink": "folHlink",
    }

    def word_color(n, attr="val", theme_attr="themeColor"):
        if n is None:
            return None
        key = n.get(q("w", theme_attr))
        value = theme.get(aliases.get(key, key)) if key else rgb(n.get(q("w", attr)))
        if theme_attr == "themeFill" and any(
            n.get(q("w", a)) for a in ("themeFillTint", "themeFillShade")
        ):
            return None
        if value and key:
            channels = [int(value[i : i + 2], 16) for i in (0, 2, 4)]
            for name in ("themeShade", "themeTint"):
                raw = n.get(q("w", name))
                if raw:
                    try:
                        amount = int(raw, 16) / 255
                    except ValueError:
                        return None
                    channels = [
                        (
                            c * amount
                            if name == "themeShade"
                            else c + (255 - c) * (1 - amount)
                        )
                        for c in channels
                    ]
            value = "".join(f"{round(c):02X}" for c in channels)
        return value

    def shading(n):
        if n is None:
            return False, None
        if n.get(q("w", "val"), "clear") not in {"clear", "nil"}:
            return True, None
        if n.get(q("w", "val")) == "nil":
            return False, None
        value = word_color(n, "fill", "themeFill")
        if n.get(q("w", "fill")) == "auto" and not n.get(q("w", "themeFill")):
            return False, None
        return True, value

    def first(props, name):
        return next((child(p, name) for p in props if child(p, name) is not None), None)

    page = pkg.roots[pkg.main]
    page_bg = child(page, "background")
    background = word_color(page_bg, "color") if page_bg is not None else "FFFFFF"
    if page_bg is not None and len(page_bg):
        background = None
    # Floating content can cover text; conditional table formatting is not resolved.
    uncertain = any(
        descendants(root, name)
        for root in (page, paragraph.getroottree().getroot())
        for name in ("anchor", "pict")
    )
    ancestors = list(paragraph.iterancestors())
    table = next((n for n in ancestors if local(n) == "tbl"), None)
    if table is not None:
        if child(child(table, "tblPr"), "tblStyle") is not None:
            uncertain = True
        present, bg = shading(child(child(table, "tblPr"), "shd"))
        if present:
            background = bg
        cell = next((n for n in ancestors if local(n) == "tc"), None)
        present, bg = shading(child(child(cell, "tcPr"), "shd"))
        if present:
            background = bg
    present, bg = shading(first([ppr] + [child(s, "pPr") for s in pchain], "shd"))
    if present:
        background = bg
    samples = []
    for run in paragraph.iter(q("w", "r")):
        # Nested text boxes are inspected as their own paragraphs.
        if (
            next((n for n in run.iterancestors() if n.tag == q("w", "p")), None)
            is not paragraph
        ):
            continue
        content = text(run)
        if not content.strip():
            continue
        rpr = child(run, "rPr")
        rstyle = child(rpr, "rStyle")
        props = (
            [rpr]
            + [
                child(s, "rPr")
                for s in chain(
                    rstyle.get(q("w", "val")) if rstyle is not None else None
                )
            ]
            + [child(s, "rPr") for s in pchain]
            + [defaults]
        )
        fg = word_color(first(props, "color"))
        if any(
            local(n)
            in {
                "textFill",
                "textOutline",
                "shadow",
                "glow",
                "reflection",
                "emboss",
                "imprint",
                "outline",
            }
            for prop in props
            if prop is not None
            for n in prop
        ):
            fg = None
        sz = first(props, "sz")
        bold_node = first(props, "b")
        try:
            size = float(sz.get(q("w", "val"))) / 2 if sz is not None else None
        except (TypeError, ValueError):
            size = None
        default_b = child(defaults, "b")
        bold = on(default_b.get(q("w", "val"), "1")) if default_b is not None else False
        rchain = chain(rstyle.get(q("w", "val")) if rstyle is not None else None)
        for style in list(reversed(pchain)) + list(reversed(rchain)):
            toggle = child(child(style, "rPr"), "b")
            if toggle is not None and on(toggle.get(q("w", "val"), "1")):
                bold = not bold
        direct_b = child(rpr, "b")
        if direct_b is not None:
            bold = on(direct_b.get(q("w", "val"), "1"))
        if any(child(p, "vertAlign") is not None for p in props if p is not None):
            size = None
        bg = background
        present, shade = shading(first(props, "shd"))
        if present:
            bg = shade
        highlight = first(props, "highlight")
        if highlight is not None and highlight.get(q("w", "val")) != "none":
            bg = None
        complex_script = any(
            child(p, name) is not None
            for p in props
            if p is not None
            for name in ("rtl", "cs", "szCs")
        ) and any(ord(c) > 127 for c in content)
        if complex_script:
            size = None
        if uncertain:
            bg = None
        samples.append(sample(content, fg, bg, size, bold))
    return samples


def pptx_context(pkg, part, shape, chain, inherited, master_part):
    theme_root = None
    if master_part:
        rel = next(
            (
                r
                for r in pkg.relationships(master_part).values()
                if r["type"].endswith("/theme") and not r["external"]
            ),
            None,
        )
        if rel:
            theme_root = pkg.xml(rel["part"])
    theme = theme_colors(theme_root)
    chain_parts = [
        name
        for name, root in pkg.roots.items()
        if any(root is ancestor for ancestor in chain)
    ]
    if any(
        r["type"].endswith("/themeOverride")
        for name in chain_parts
        for r in pkg.relationships(name).values()
    ):
        theme = {}  # Overrides are preserved; do not use stale master colors.
    mapping = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
    for root in reversed(chain):
        if root is None:
            continue
        for name in ("clrMap", "overrideClrMapping"):
            for n in descendants(root, name):
                mapping.update(n.attrib)

    def reference(ref, background=False):
        if ref is None or theme_root is None:
            return None
        try:
            index = int(ref.get("idx", "0"))
        except ValueError:
            return None
        name = "bgFillStyleLst" if index >= 1001 else "fillStyleLst"
        idx = index - 1001 if index >= 1001 else index - 1
        listing = next(iter(descendants(theme_root, name)), None)
        if listing is None or not 0 <= idx < len(listing):
            return None
        node = listing[idx]
        placeholder = color(ref[0], theme, mapping) if len(ref) else None
        return (
            color(node[0], theme, mapping, placeholder)
            if local(node) == "solidFill" and len(node) == 1
            else None
        )

    bg = None
    for root in chain:
        node = child(child(root, "cSld"), "bg")
        if node is not None:
            props = child(node, "bgPr")
            _, bg = fill(props, theme, mapping)
            if props is None:
                bg = reference(child(node, "bgRef"), True)
            break
    sppr = child(shape, "spPr")
    found, own = fill(sppr, theme, mapping)
    if found and child(sppr, "noFill") is None:
        bg = own
    elif not found:
        ref = child(child(shape, "style"), "fillRef")
        if ref is not None and ref.get("idx", "0") != "0":
            bg = reference(ref)
        elif inherited:
            for ancestor in inherited:
                found, own = fill(child(ancestor, "spPr"), theme, mapping)
                if found:
                    if child(child(ancestor, "spPr"), "noFill") is None:
                        bg = own
                    break

    # Only plain text shapes with unambiguous non-overlapping bounds are measured.
    def bounds(node):
        x = child(child(node, "spPr"), "xfrm")
        if x is None:
            return None
        if x.get("rot", "0") != "0":
            return None
        off, ext = child(x, "off"), child(x, "ext")
        try:
            return tuple(
                int(n.get(a))
                for n, a in ((off, "x"), (off, "y"), (ext, "cx"), (ext, "cy"))
            )
        except (AttributeError, TypeError, ValueError):
            return None

    box = bounds(shape)
    if box is None:
        box = next((bounds(n) for n in inherited if bounds(n) is not None), None)
    uncertain = (
        local(shape) != "sp"
        or box is None
        or any(local(n) == "grpSp" for n in shape.iterancestors())
    )
    for root in chain:
        tree = child(child(root, "cSld"), "spTree")
        for other in tree if tree is not None else []:
            if (
                other is shape
                or any(other is n for n in inherited)
                or local(other) not in {"sp", "pic", "graphicFrame", "grpSp", "cxnSp"}
            ):
                continue
            if descendants(other, "ph") and root is not chain[0]:
                continue
            other_box = bounds(other)
            if other_box is None:
                uncertain = True
                continue
            if (
                box
                and box[0] < other_box[0] + other_box[2]
                and other_box[0] < box[0] + box[2]
                and box[1] < other_box[1] + other_box[3]
                and other_box[1] < box[1] + box[3]
            ):
                uncertain = True
    if any(descendants(shape, n) for n in ("effectLst", "effectDag", "highlight")):
        uncertain = True
    return {
        "theme": theme,
        "mapping": mapping,
        "background": None if uncertain else bg,
        "shape": shape,
    }


def pptx_sample(run, candidates, size, context):
    fg = None
    found = False
    for props in candidates:
        found, fg = fill(props, context["theme"], context["mapping"])
        if found:
            break
    if not found:
        ref = child(child(context["shape"], "style"), "fontRef")
        if ref is not None and len(ref):
            fg = color(ref[0], context["theme"], context["mapping"])
    bold = next((on(n.get("b")) for n in candidates if n.get("b") is not None), None)
    if any(n.get("baseline", "0") != "0" for n in candidates):
        size = None
    if child(run, "rPr") is not None and any(
        local(n) in {"highlight", "effectLst", "effectDag"} for n in child(run, "rPr")
    ):
        fg = None
    return sample(text(run), fg, context["background"], size, bold)


def apply_formatting(pkg, node, action, value):
    """Set only the selected property on existing text runs; keep text/runs intact."""
    from .repairs import ensure

    prefix = "w" if pkg.format == "docx" else "a"
    runs = list(node.iter(q(prefix, "r")))
    if prefix == "a":
        runs += list(node.iter(q("a", "fld")))
    for run in runs:
        if not text(run).strip():
            continue
        if (
            prefix == "w"
            and next((n for n in run.iterancestors() if n.tag == q("w", "p")), None)
            is not node
        ):
            continue
        props = ensure(run, q(prefix, "rPr"), first=True)
        if action == "set_font_size":
            if prefix == "w":
                # CT_RPr handles schema order without rebuilding runs.
                from docx.oxml import parse_xml

                native = parse_xml(ET.tostring(props))
                size = native.get_or_add_sz()
                size.set(q("w", "val"), str(round(float(value) * 2)))
                complex_size = child(native, "szCs")
                if complex_size is None:
                    complex_size = ET.Element(q("w", "szCs"))
                    native.insert(list(native).index(size) + 1, complex_size)
                complex_size.set(q("w", "val"), str(round(float(value) * 2)))
                props.getparent().replace(props, native)
            else:
                props.set("sz", str(round(float(value) * 100)))
        elif prefix == "w":
            from docx.oxml import parse_xml

            native = parse_xml(ET.tostring(props))
            target = native.get_or_add_color()
            for name in ("themeColor", "themeTint", "themeShade"):
                target.attrib.pop(q("w", name), None)
            target.set(q("w", "val"), value.lstrip("#").upper())
            props.getparent().replace(props, native)
        else:
            for old in list(props):
                if local(old) in {
                    "solidFill",
                    "gradFill",
                    "blipFill",
                    "pattFill",
                    "grpFill",
                    "noFill",
                }:
                    props.remove(old)
            solid = ET.Element(q("a", "solidFill"))
            ET.SubElement(solid, q("a", "srgbClr"), val=value.lstrip("#").upper())
            # Fill follows a line property and precedes effects/font/link properties.
            props.insert(1 if len(props) and local(props[0]) == "ln" else 0, solid)
