"""Exercise the actual Flask adapter without a Docassemble server."""
import base64
import io
import json
import sys
import subprocess
from unittest.mock import patch

import pikepdf
import pytest

from web.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def pdf_bytes():
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    output = io.BytesIO()
    pdf.save(output)
    return output.getvalue()


def upload(client, route, **fields):
    return client.post("/pdf-labeler/api/accessibility-" + route, data={
        "file": (io.BytesIO(pdf_bytes()), "sample.pdf"), **fields,
    })


def test_home_and_only_workshop_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b'id="a11y-workshop"' in page.data
    assert b"Field editor" not in page.data
    assert client.get("/assets/pdf_labeler.js").status_code == 404
    assert client.get("/assets/pdf_accessibility_workshop.js").status_code == 200
    # The repository's pytest conftest imports Docassemble; use a fresh process.
    subprocess.run([sys.executable, "-c",
                    "from web.app import app; import sys; "
                    "assert 'docassemble.base' not in sys.modules"], check=True)


def test_inspect_and_metadata_round_trip(client):
    assert upload(client, "inspect").json["success"]
    response = upload(client, "remediate", action="metadata",
                      metadata=json.dumps({"title": "Accessible sample", "language": "en-US"}))
    assert response.status_code == 200
    data = response.json["data"]
    with pikepdf.open(io.BytesIO(base64.b64decode(data["pdf_base64"]))) as pdf:
        assert str(pdf.docinfo.Title) == "Accessible sample"
        assert str(pdf.Root.Lang) == "en-US"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("route", ["font-review", "font-substitutes", "image-previews"])
def test_review_endpoints(client, route):
    assert upload(client, route).json["success"]


def test_validation_and_cross_origin(client):
    assert client.post("/pdf-labeler/api/accessibility-inspect").status_code == 400
    assert upload(client, "remediate", action="certify").status_code == 400
    assert upload(client, "remediate", action="metadata", metadata="{").status_code == 400
    assert client.post("/pdf-labeler/api/accessibility-inspect",
                       headers={"Origin": "https://other.example"}).status_code == 403
    assert client.post("/pdf-labeler/api/accessibility-inspect",
                       headers={"Origin": "https://localhost", "X-Forwarded-Proto": "https"}).status_code == 400


def test_ai_requires_configuration_and_uses_server_model(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    url = "/pdf-labeler/api/accessibility-ai-tooltips"
    assert client.post(url, json={"fields": []}).status_code == 503
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    with patch("workshop.pdf_accessibility.draft_field_tooltips_with_ai",
               return_value={"name": "Name"}) as draft:
        response = client.post(url, json={"fields": [{"name": "name"}], "model": "unapproved"})
    assert response.json["data"]["review_required"] is True
    assert draft.call_args.kwargs["model"] == "gpt-5-mini"


def test_direct_ai_transport_in_standalone_context(monkeypatch):
    from types import SimpleNamespace
    from workshop.workshop_ai import chat_completion

    monkeypatch.delenv("WORKSHOP_STANDALONE", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    choice = SimpleNamespace(finish_reason="stop",
                             message=SimpleNamespace(content='{"tooltips": []}'))
    with app.app_context(), patch("openai.OpenAI") as provider:
        create = provider.return_value.chat.completions.create
        create.return_value = SimpleNamespace(choices=[choice])
        assert chat_completion(messages=[], json_mode=True, temperature=0,
                               max_output_tokens=8192) == '{"tooltips": []}'
        assert create.call_args.kwargs["response_format"] == {"type": "json_object"}
        assert "temperature" not in create.call_args.kwargs
        choice.finish_reason = "length"
        with pytest.raises(ValueError, match="complete answer"):
            chat_completion(messages=[])
