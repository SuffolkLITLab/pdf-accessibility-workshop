import json
import os
from pathlib import Path
import pytest
from workshop.validation import validate_pdf


@pytest.mark.parametrize(
    "report,expected",
    [
        (
            {
                "profileName": "PDF/UA-1 validation profile",
                "compliant": True,
                "jobEndStatus": "normal",
            },
            "pass",
        ),
        (
            {
                "profileName": "PDF/UA-1 validation profile",
                "compliant": False,
                "jobEndStatus": "normal",
            },
            "fail",
        ),
        ({"profileName": "PDF/A-1b validation profile", "compliant": True}, "error"),
        (
            {
                "profileName": "PDF/UA-1 validation profile",
                "compliant": True,
                "jobEndStatus": "failed",
            },
            "error",
        ),
        ({"profileName": "PDF/UA-1 validation profile", "isCompliant": True}, "pass"),
        ({"profileName": "PDF/UA-1 validation profile", "compliant": "true"}, "error"),
    ],
)
def test_validation_evidence_is_profile_specific(tmp_path, report, expected):
    binary = tmp_path / "validator"
    binary.write_text(
        '#!/usr/bin/env python3\nimport sys,json\nif "--version" in sys.argv: print("fixture 1.0")\nelse: print('
        + repr(json.dumps({"validationResult": [report]}))
        + ")\n"
    )
    binary.chmod(0o755)
    result = validate_pdf(b"%PDF-fixture", executable=str(binary))
    assert result["outcome"] == expected
    assert (
        result["source_sha256"]
        and result["raw_report"]
        and result["tool_version"] == "fixture 1.0"
    )


def test_missing_unsupported_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("workshop.validation.shutil.which", lambda _: None)
    assert validate_pdf(b"%PDF-")["outcome"] == "not_run"
    assert validate_pdf(b"%PDF-", "auto")["outcome"] == "unsupported"
    binary = tmp_path / "slow"
    binary.write_text(
        '#!/usr/bin/env python3\nimport sys,time\nif "--version" in sys.argv:print("fixture")\nelse:time.sleep(2)\n'
    )
    binary.chmod(0o755)
    assert (
        validate_pdf(b"%PDF-", executable=str(binary), timeout=0.05)["outcome"]
        == "error"
    )


def test_real_verapdf_when_available():
    executable = os.environ.get("VERAPDF_TEST_EXECUTABLE")
    if not executable:
        pytest.skip("Set VERAPDF_TEST_EXECUTABLE to run the real capability spike.")
    assert (
        validate_pdf(
            Path("tests/plain-document.pdf").read_bytes(), executable=executable
        )["outcome"]
        == "fail"
    )
    assert validate_pdf(b"%PDF-broken", executable=executable)["outcome"] == "error"
