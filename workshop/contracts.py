"""Format-neutral evidence and immutable, content-addressed versions."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import uuid

SCHEMA_VERSION = 1
ENGINE_VERSION = "office-1.0"
OUTCOMES = {
    "pass",
    "fail",
    "needs_review",
    "not_applicable",
    "not_run",
    "unsupported",
    "error",
}


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


@dataclass(frozen=True)
class DocumentVersion:
    id: str
    sha256: str
    filename: str
    format: str
    parent_version: str | None = None

    @classmethod
    def from_bytes(cls, data, filename, format, parent_version=None):
        checksum = digest(data)
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, checksum))
        return cls(identity, checksum, filename, format, parent_version)

    def to_dict(self):
        return asdict(self)


def summary(findings):
    return {
        "problems_found": sum(f["outcome"] == "fail" for f in findings),
        "review_remaining": sum(f["outcome"] == "needs_review" for f in findings),
        "checks_unavailable": sum(
            f["outcome"] in {"not_run", "unsupported", "error"} for f in findings
        ),
    }


# These mappings describe relevance, not conformance claims.
RULE_REFERENCES = {
    "images": ("1.1.1", "Text alternatives require contextual human review."),
    "structure": (
        "1.3.1",
        "Native structure is evidence of relationships; semantics need review.",
    ),
    "order": ("1.3.2", "Native sequence does not prove meaningful reading order."),
    "language": ("3.1.1", "Effective text language helps readers select a voice."),
    "links": ("2.4.4", "Link purpose depends on the label and its context."),
    "metadata": ("2.4.2", "A descriptive title identifies the document."),
    "contrast": (
        "1.4.3",
        "Only resolved foreground/background pairs support a contrast measurement.",
    ),
    "media": (
        "1.2.2",
        "Caption presence alone cannot establish caption accuracy or sufficiency.",
    ),
}
