import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import pytest
from workshop.office.ai_drafts import draft_repairs
from workshop.office.engine import OfficeEngine
from workshop.office.package import Conflict, PackageError
from workshop.contracts import digest
from workshop.usage import reserve, UsageError
from tests.test_office import docx_bytes


def test_ai_proposals_are_validated_and_never_modify_source(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    source = docx_bytes()
    before = digest(source)
    objects = OfficeEngine().inspect(source, "Instructions.docx")["objects"]
    title = next(o for o in objects if o["kind"] == "metadata")
    paragraph = next(o for o in objects if o["kind"] == "paragraph")
    response = {
        "suggestions": [
            {
                "object_id": title["id"],
                "action": "set_title",
                "value": "Application instructions",
                "reason": "Use the visible title.",
            },
            {
                "object_id": paragraph["id"],
                "action": "set_paragraph_role",
                "value": "heading1",
                "reason": "Main heading.",
            },
            {"object_id": "invented", "action": "set_title", "value": "Not permitted"},
            {
                "object_id": paragraph["id"],
                "action": "set_link_text",
                "value": "Changed text",
            },
        ],
        "review_notes": ["Review spacing manually."],
    }
    with patch(
        "workshop.office.ai_drafts.chat_completion", return_value=json.dumps(response)
    ) as provider:
        with pytest.raises(Conflict):
            draft_repairs(source, "Instructions.docx", "stale")
        provider.assert_not_called()
        result = draft_repairs(source, "Instructions.docx", before)
    assert digest(source) == before
    assert result["draft"] and result["source_sha256"] == before
    assert len(result["suggestions"]) == 2 and result["excluded_proposals"] == 2
    assert "{{ users[0].name }}" in json.dumps(provider.call_args.kwargs["messages"])
    assert provider.call_args.kwargs["max_output_tokens"] == 6000


def test_provider_failures_do_not_leak_details(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    source = docx_bytes()
    with patch(
        "workshop.office.ai_drafts.chat_completion",
        side_effect=RuntimeError("private provider detail"),
    ):
        with pytest.raises(PackageError, match="temporarily unavailable") as error:
            draft_repairs(source, "Instructions.docx", digest(source))
        assert "private" not in str(error.value)


def test_durable_atomic_allowance(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSHOP_LIMITS_ENABLED", "1")
    monkeypatch.setenv("WORKSHOP_USAGE_DB", str(tmp_path / "usage.sqlite"))
    monkeypatch.setenv("AI_CALLS_PER_DAY", "3")

    def attempt(i):
        try:
            reserve("ai", identity=str(i), now=172800)
            return True
        except UsageError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 3
    with pytest.raises(UsageError):
        reserve("ai", identity="new-client", now=172801)
    reserve("ai", identity="new-client", now=259200)
    assert b"new-client" not in (tmp_path / "usage.sqlite").read_bytes()


def test_api_rate_limits_and_fail_closed_ai(monkeypatch, tmp_path):
    from web.app import app

    monkeypatch.setenv("WORKSHOP_LIMITS_ENABLED", "1")
    monkeypatch.setenv("WORKSHOP_USAGE_DB", str(tmp_path / "usage.sqlite"))
    monkeypatch.setenv("API_REQUESTS_PER_MINUTE", "1")
    client = app.test_client()
    assert client.post("/api/documents/inspect").status_code == 400
    response = client.post("/api/documents/inspect")
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    monkeypatch.setenv("WORKSHOP_USAGE_DB", str(tmp_path / "missing" / "usage.sqlite"))
    with pytest.raises(UsageError, match="unavailable"):
        reserve("ai")
    reserve("api")  # Manual review is available if the counter store fails.


def test_transport_bounds_and_disables_provider_retries(monkeypatch):
    from types import SimpleNamespace
    from workshop.workshop_ai import chat_completion

    monkeypatch.setenv("WORKSHOP_LIMITS_ENABLED", "0")
    result = SimpleNamespace(
        choices=[
            SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="{}"))
        ]
    )
    with patch("openai.OpenAI") as provider:
        provider.return_value.chat.completions.create.return_value = result
        chat_completion(
            messages=[{"role": "user", "content": "Return JSON"}],
            max_output_tokens=30000,
        )
        assert provider.call_args.kwargs["max_retries"] == 0
        assert (
            provider.return_value.chat.completions.create.call_args.kwargs[
                "max_completion_tokens"
            ]
            == 8192
        )
        with pytest.raises(UsageError):
            chat_completion(messages=[{"role": "user", "content": "a" * 100001}])
        assert provider.return_value.chat.completions.create.call_count == 1


def test_startup_drops_privileges_after_initializing_counter_volume(
    monkeypatch, tmp_path
):
    import runpy
    import sys
    from types import SimpleNamespace

    calls = []
    monkeypatch.setenv("WORKSHOP_USAGE_DB", str(tmp_path / "counter" / "usage.sqlite"))
    monkeypatch.setattr("os.getuid", lambda: 0)
    monkeypatch.setattr(
        "pwd.getpwnam",
        lambda name: SimpleNamespace(pw_name=name, pw_uid=1000, pw_gid=1000),
    )
    for name in ("chown", "chmod", "initgroups", "setgid", "setuid", "execvp"):
        monkeypatch.setattr(
            "os." + name, lambda *args, name=name: calls.append((name, args))
        )
    monkeypatch.setattr(sys, "argv", ["start_server.py", "gunicorn", "web.app:app"])
    runpy.run_path("scripts/start_server.py")
    assert [name for name, _ in calls] == [
        "chown",
        "chmod",
        "initgroups",
        "setgid",
        "setuid",
        "execvp",
    ]
    assert calls[-1][1] == ("gunicorn", ["gunicorn", "web.app:app"])
