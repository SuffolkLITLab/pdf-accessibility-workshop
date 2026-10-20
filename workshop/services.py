"""Shared inspection/export services. No Flask imports and no implicit AI calls."""

import base64
import html
import io
import json
from pathlib import Path
import shutil
import tempfile
import zipfile
from workshop.contracts import DocumentVersion, ENGINE_VERSION, digest, summary
from workshop.office.engine import OfficeEngine
from workshop.office.package import PackageError


def inspect_document(source, filename):
    if source.startswith(b"%PDF-"):
        from workshop.pdf_accessibility import inspect_pdf_accessibility

        with tempfile.TemporaryDirectory(prefix="pdf-inspect-") as folder:
            path = Path(folder) / "input.pdf"
            path.write_bytes(source)
            raw = inspect_pdf_accessibility(str(path))
            from workshop.pdf_policy import pdf_edit_policy

            policy = pdf_edit_policy(path)
        version = DocumentVersion.from_bytes(source, filename, "pdf").to_dict()
        findings = []
        for row in raw.get("report", {}).get("issues", []):
            findings.append(
                {
                    "id": row["id"],
                    "rule_id": "pdf." + row["id"],
                    "source_code": row.get("rule"),
                    "severity": (
                        "warning" if row.get("severity") == "warning" else "error"
                    ),
                    "outcome": {"review": "needs_review"}.get(
                        row.get("status"), row.get("status", "not_run")
                    ),
                    "message": row.get("title", ""),
                    "document_version": version["id"],
                    "source_sha256": version["sha256"],
                    "target": None,
                    "location_label": "Aggregate PDF check; use the PDF workshop’s native objects",
                    "repair_options": [],
                    "evidence": row,
                }
            )
        coverage = [
            {
                "capability": name,
                "outcome": "needs_review" if shutil.which(executable) else "not_run",
                "detail": (
                    "Tool installed; individual analysis availability remains in native evidence."
                    if shutil.which(executable)
                    else "Tool unavailable; related layout/text coverage is incomplete."
                ),
            }
            for name, executable in [
                ("layout_text", "pdftohtml"),
                ("text_extraction", "pdftotext"),
                ("ocr", "tesseract"),
            ]
        ]
        if raw.get("readback", {}).get("available") is False:
            coverage.append(
                {
                    "capability": "readback",
                    "outcome": "not_run",
                    "detail": "Native readback reported unavailable.",
                }
            )
        return {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "version": version,
            "format": "pdf",
            "findings": findings,
            "coverage": coverage,
            "summary": summary(findings),
            "native_report": raw,
            "edit_policy": policy,
            "objects": [],
            "external_validation": [],
            "reader_tests": [],
        }
    return OfficeEngine().inspect(source, filename)


def export_bundle(source, filename, evidence):
    report = inspect_document(source, filename)
    checksum = digest(source)
    supplied_version = evidence.get("version")
    if supplied_version:
        if (
            supplied_version.get("sha256") != checksum
            or supplied_version.get("id") != report["version"]["id"]
        ):
            raise PackageError("Version evidence does not match the exported bytes.")
        report["version"]["parent_version"] = supplied_version.get("parent_version")
    if evidence.get("source_sha256") != checksum:
        raise PackageError(
            "Review evidence belongs to different bytes. Reinspect before exporting."
        )
    # Human/external records stay separate from automated findings. Preserve
    # historical evidence with its original digest; never label it current.
    decisions = evidence.get("human_decisions", [])
    external = evidence.get("external_tests", [])
    if (
        not isinstance(decisions, list)
        or not isinstance(external, list)
        or len(decisions) > 2000
        or len(external) > 100
    ):
        raise PackageError("Invalid review evidence.")
    for record in decisions + external:
        if not isinstance(record, dict) or record.get("source_sha256") != checksum:
            raise PackageError(
                "A review record targets an older version. Reconfirm it for this version."
            )
    manifest = {
        "schema_version": 1,
        "document": report["version"],
        "engine_report": report,
        "human_decisions": decisions,
        "external_tests": external,
        "repair_receipts": evidence.get("repair_receipts", []),
        "portable_snapshot": evidence.get("portable_snapshot"),
        "assurance": "Automated findings, human review, external validation and reader testing are separate. This report does not certify conformance.",
    }
    esc = lambda value: html.escape(str(value))
    rows = "".join(
        f'<tr><td>{esc(f["rule_id"])}</td><td>{esc(f["outcome"])}</td><td>{esc(f.get("location_label","Document"))}</td><td>{esc(f["message"])}</td></tr>'
        for f in report["findings"]
    )
    readable = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Accessibility review — {esc(filename)}</title>
<style>body{{font:16px/1.5 Arial,sans-serif;margin:2rem;max-width:1000px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #777;padding:.5rem;text-align:left;vertical-align:top}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
<h1>Accessibility review: {esc(filename)}</h1><p>{esc(manifest['assurance'])}</p><p>SHA-256: {checksum}</p>
<h2>Automated findings</h2><table><thead><tr><th>Rule</th><th>Outcome</th><th>Location</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Checks unavailable and coverage</h2><pre>{esc(json.dumps(report['coverage'],indent=2))}</pre>
<h2>Human decisions</h2><pre>{esc(json.dumps(decisions,indent=2))}</pre><h2>External tests (author-recorded)</h2><pre>{esc(json.dumps(external,indent=2))}</pre>
<h2>PDF workshop decisions and drafts</h2><p>Confirmed values and unconfirmed drafts retain their original flags. Unconfirmed drafts are not completed review.</p><pre>{esc(json.dumps(manifest['portable_snapshot'],indent=2))}</pre>
<h2>Repair receipts</h2><pre>{esc(json.dumps(manifest['repair_receipts'],indent=2))}</pre></html>"""
    output = io.BytesIO()
    safe = Path(filename.replace("\\", "/")).name or "document." + report["format"]
    # Avoid colliding with the report files, even for a misleading logical filename.
    safe = Path(safe).stem + "." + report["format"]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(safe, source)
        bundle.writestr(
            "review-manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False)
        )
        bundle.writestr("accessibility-review.html", readable)
        inventory = Path(__file__).resolve().parents[1] / "runtime-dependencies.json"
        if inventory.exists():
            bundle.writestr("runtime-dependencies.json", inventory.read_bytes())
    return output.getvalue()
