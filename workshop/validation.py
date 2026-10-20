"""Explicit-profile veraPDF execution, independent of HTTP and inference."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from workshop.contracts import digest


def validate_pdf(source, profile="ua1", executable=None, timeout=120):
    result = {
        "source_sha256": digest(source),
        "tool": "veraPDF",
        "profile": profile,
        "outcome": "not_run",
        "tool_version": None,
        "raw_report": None,
        "stderr": "",
        "truncated": False,
    }
    if profile not in {"ua1", "ua2"}:
        return {
            **result,
            "outcome": "unsupported",
            "detail": "Choose the explicit ua1 or ua2 profile; automatic PDF/A fallback is never used.",
        }
    binary = executable or shutil.which("verapdf")
    if not binary:
        return {
            **result,
            "detail": "veraPDF is not installed on this deployment. Run an external PDF/UA validator and record its exact artifact/profile result.",
        }
    try:
        version = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        result["tool_version"] = version.stdout.strip()[:500]
        with tempfile.TemporaryDirectory(prefix="verapdf-") as folder:
            path = Path(folder) / "input.pdf"
            path.write_bytes(source)
            # Files bound memory use; job-level execution timeout bounds subprocess lifetime.
            stdout_path = Path(folder) / "stdout.json"
            stderr_path = Path(folder) / "stderr.txt"
            with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
                process = subprocess.run(
                    [binary, "--flavour", profile, "--format", "json", str(path)],
                    stdout=out,
                    stderr=err,
                    timeout=timeout,
                    check=False,
                )
            if stdout_path.stat().st_size > 8 * 1024 * 1024:
                return {
                    **result,
                    "outcome": "error",
                    "truncated": True,
                    "detail": "Validator report exceeded 8 MB; no passing result was inferred.",
                }
            raw = stdout_path.read_text(errors="replace")
            stderr = stderr_path.read_text(errors="replace")
        result["stderr"] = stderr[:4000]
        result["raw_report"] = raw
        if process.returncode not in {0, 1}:
            return {
                **result,
                "outcome": "error",
                "detail": "Validator processing failed; inspect its raw report.",
            }
        parsed = json.loads(raw)
        reports = []

        def collect(value):
            if isinstance(value, dict):
                if "isCompliant" in value or (
                    "compliant" in value and "profileName" in value
                ):
                    reports.append(value)
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(parsed)
        if not reports or any(
            not isinstance(r.get("isCompliant", r.get("compliant")), bool)
            or r.get("jobEndStatus", "normal") != "normal"
            for r in reports
        ):
            return {
                **result,
                "outcome": "error",
                "detail": "No recognized PDF/UA validation result in the response.",
            }
        # Require the returned profile to agree with the requested one, rather
        # than treating a PDF/A fallback or unknown report as PDF/UA evidence.
        expected = "PDF/UA-" + profile[-1]
        if any(
            expected.lower() not in str(r.get("profileName", "")).lower()
            for r in reports
        ):
            return {
                **result,
                "outcome": "error",
                "detail": "The returned profile could not be verified as "
                + expected
                + ".",
            }
        result["truncated"] = any(
            rule.get("failedChecks", 0) > len(rule.get("checks", []))
            for report in reports
            for rule in report.get("details", {}).get("ruleSummaries", [])
        )
        return {
            **result,
            "outcome": (
                "pass"
                if all(r.get("isCompliant", r.get("compliant")) for r in reports)
                else "fail"
            ),
            "detail": "Machine-verifiable checks only; semantic and reader testing remain separate.",
        }
    except subprocess.TimeoutExpired:
        return {
            **result,
            "outcome": "error",
            "detail": "Validator timed out; the previous usable document is unchanged.",
        }
    except (OSError, ValueError):
        return {
            **result,
            "outcome": "error",
            "detail": "Validator output could not be processed.",
        }
