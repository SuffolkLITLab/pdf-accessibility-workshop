"""Bounded OPC ZIP/XML reader; never fetch external relationships."""

import io
import posixpath
import zipfile
from urllib.parse import unquote
from lxml import etree as ET
from workshop.contracts import digest

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "dc": "http://purl.org/dc/elements/1.1/",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "adec": "http://schemas.microsoft.com/office/drawing/2017/decorative",
}


def q(prefix, local):
    return "{" + NS[prefix] + "}" + local


def local(node):
    return ET.QName(node).localname if isinstance(node.tag, str) else ""


def elements(node):
    return [child for child in node if isinstance(child.tag, str)]


def descendants(node, name):
    return [el for el in node.iter() if local(el) == name]


def text(node):
    return "".join(el.text or "" for el in node.iter() if local(el) in {"t", "delText"})


def on(value):
    return value is None or str(value).lower() in {"1", "true", "on"}


class PackageError(ValueError):
    pass


class Conflict(PackageError):
    pass


class Package:
    def __init__(self, data: bytes):
        if len(data) > 30 * 1024 * 1024:
            raise PackageError("Files must be smaller than 30 MB.")
        self.data = data
        self.roots = {}
        self.errors = {}
        self.changed = set()
        self.element_paths = {}
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
            self.infos = archive.infolist()
            if (
                len(self.infos) > 5000
                or sum(i.file_size for i in self.infos) > 150 * 1024 * 1024
            ):
                raise PackageError(
                    "The expanded package exceeds the inspection budget."
                )
            self.members = {}
            for info in self.infos:
                name = info.filename
                if (
                    name in self.members
                    or name.startswith("/")
                    or ".." in name.split("/")
                    or "\\" in name
                ):
                    raise PackageError(
                        "The ZIP contains duplicate or unsafe member names."
                    )
                if info.flag_bits & 1 or info.file_size > 25 * 1024 * 1024:
                    raise PackageError(
                        "Encrypted or oversized ZIP members are unsupported."
                    )
                self.members[name] = archive.read(info)
            archive.close()
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            raise PackageError(
                "This is not a readable DOCX or PPTX package; encrypted Office files require an unprotected copy."
            ) from exc
        self.format = (
            "docx"
            if "word/document.xml" in self.members
            else "pptx" if "ppt/presentation.xml" in self.members else ""
        )
        if not self.format or "[Content_Types].xml" not in self.members:
            raise PackageError(
                "The file is not a supported native DOCX or PPTX package."
            )
        self.main = (
            "word/document.xml" if self.format == "docx" else "ppt/presentation.xml"
        )
        self.xml("[Content_Types].xml", required=True)
        self.xml(self.main, required=True)
        if (
            ET.QName(self.roots[self.main]).namespace
            != NS["w" if self.format == "docx" else "p"]
        ):
            raise PackageError(
                "Strict or unknown OOXML namespaces are not supported; save a standard DOCX/PPTX copy in the native application."
            )
        content_types = self.roots["[Content_Types].xml"]
        expected = (
            "wordprocessingml.document.main+xml"
            if self.format == "docx"
            else "presentationml.presentation.main+xml"
        )
        if not any(
            expected in el.get("ContentType", "")
            and el.get("PartName", "").lstrip("/") == self.main
            for el in content_types
        ):
            raise PackageError(
                "The package content type does not match DOCX/PPTX (macros and templates are unsupported)."
            )
        if any("vbaProject" in name for name in self.members):
            raise PackageError("Macro-bearing packages are not supported.")
        for name in self.members:
            if name.endswith((".xml", ".rels")):
                self.xml(name)
        self.xml("_rels/.rels", required=True)
        root_rels = self.relationships("")
        if not any(
            r["part"] == self.main
            and not r["external"]
            and r["type"].endswith("/officeDocument")
            for r in root_rels.values()
        ):
            raise PackageError(
                "The required package relationship to the main document is missing."
            )
        self.external = []
        for name in self.members:
            if name.endswith(".rels"):
                part = (
                    ""
                    if name == "_rels/.rels"
                    else posixpath.join(
                        posixpath.dirname(posixpath.dirname(name)),
                        posixpath.basename(name)[:-5],
                    )
                )
                for rel in self.relationships(part).values():
                    if rel["external"]:
                        self.external.append({"part": part, **rel})
                    elif rel["part"] not in self.members:
                        self.errors[name] = (
                            "An internal relationship points to a missing package part."
                        )
        for part, root in list(self.roots.items()):
            if not part.endswith(".xml"):
                continue
            rels = self.relationships(part)
            for node in root.iter():
                for attribute, rid in node.attrib.items():
                    if (
                        attribute in {q("r", "id"), q("r", "embed"), q("r", "link")}
                        and rid
                        and rid not in rels
                    ):
                        self.errors[part] = (
                            "A native object references a missing relationship; coverage is incomplete."
                        )
        if self.main.startswith("ppt/"):
            # Presentation order depends on these relationships, so they are required.
            self.xml("ppt/_rels/presentation.xml.rels", required=True)
        self.signed = any(name.startswith("_xmlsignatures/") for name in self.members)
        self.protected = any(
            local(el) in {"documentProtection", "writeProtection", "modifyVerifier"}
            and on(el.get(q("w", "enforcement"), "1"))
            for root in self.roots.values()
            for el in root.iter()
        )

    def xml(self, name, required=False):
        if name in self.roots:
            return self.roots[name]
        if name not in self.members:
            if required:
                raise PackageError(f"Required part is missing: {name}")
            return None
        try:
            parser = ET.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                huge_tree=False,
                remove_blank_text=False,
                strip_cdata=False,
            )
            root = ET.fromstring(self.members[name], parser)
            if root.getroottree().docinfo.doctype:
                raise ValueError("DTD declarations are not supported")
            if sum(1 for _ in root.iter()) > 200000:
                raise ValueError("XML element budget exceeded")
            self.roots[name] = root
            return root
        except (ET.XMLSyntaxError, ValueError) as exc:
            self.errors[name] = (
                "Malformed or unsupported XML; this part was not inspected."
            )
            if required:
                raise PackageError(
                    f"Required XML is malformed or unsupported: {name}"
                ) from exc
            return None

    def relationships(self, part):
        name = (
            posixpath.join(
                posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
            )
            if part
            else "_rels/.rels"
        )
        root = self.xml(name)
        if root is None:
            return {}
        result = {}
        for el in root:
            target = unquote(el.get("Target", ""))
            external = el.get("TargetMode") == "External"
            resolved = (
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.normpath(
                    posixpath.join(posixpath.dirname(part), target.split("#")[0])
                )
            )
            if not external and (resolved.startswith("../") or ":" in resolved):
                self.errors[name] = "Unsafe internal relationship target."
                continue
            result[el.get("Id")] = {
                "target": target,
                "part": resolved,
                "external": external,
                "type": el.get("Type", ""),
            }
        return result

    def path(self, part, element):
        if part not in self.element_paths:
            paths = {}
            stack = [(self.roots[part], "")]
            while stack:
                node, path = stack.pop()
                paths[node] = path
                stack.extend(
                    (child, path + "/" + str(index))
                    for index, child in enumerate(elements(node))
                )
            self.element_paths[part] = paths
        try:
            return self.element_paths[part][element]
        except KeyError as exc:
            raise PackageError("Target does not belong to the requested part.") from exc

    def target(self, part, element):
        return {
            "format": self.format,
            "part": part,
            "element_path": self.path(part, element),
            "object_id": element.get("id")
            or element.get(
                "{http://schemas.microsoft.com/office/word/2010/wordml}paraId"
            ),
            "fingerprint": digest(ET.tostring(element, with_tail=False)),
        }

    def locate(self, target, validate=True):
        root = self.xml(target["part"], required=True)
        node = root
        try:
            for index in target["element_path"].split("/"):
                if index:
                    node = elements(node)[int(index)]
        except (IndexError, ValueError, KeyError) as exc:
            raise Conflict(
                "The target no longer exists; inspect the current version again."
            ) from exc
        if (
            validate
            and digest(ET.tostring(node, with_tail=False)) != target["fingerprint"]
        ):
            raise Conflict("The target changed; inspect the current version again.")
        return node

    def touch(self, part):
        self.changed.add(part)

    def write(self):
        if not self.changed:
            return self.data
        replacements = {
            name: ET.tostring(
                self.roots[name],
                xml_declaration=True,
                encoding="UTF-8",
                standalone=True,
            )
            for name in self.changed
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for info in self.infos:
                archive.writestr(
                    info, replacements.get(info.filename, self.members[info.filename])
                )
            for name in sorted(self.changed - self.members.keys()):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, replacements[name])
        return output.getvalue()
