"""Standalone HTTP adapters for the workshop's stateless PDF operations.

The PDF engine and browser UI are shared with ALDashboard. This module has
no dependency on the Docassemble runtime, authentication, Redis or workers.
"""
import base64
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from flask import Blueprint, Response, current_app, jsonify, request

app = Blueprint("workshop_api", __name__)
LABELER_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")

class DashboardAPIValidationError(ValueError):
    def __init__(self, message, status_code=400):
        self.message, self.status_code = message, status_code
        super().__init__(message)

def jsonify_with_status(body, status):
    return jsonify(body), status

def log(message, level):
    # Do not put uploaded document data or provider exception details in logs.
    current_app.logger.log(40 if level == "error" else 20, "Workshop request completed with %s", level)

def parse_bool(value, default=False):
    if value is None:
        return default
    return value is True or str(value).lower() in {"true", "1", "yes"}

def _parse_optional_json_field(value, *, field_name):
    if value is None or value == "":
        return None
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        raise DashboardAPIValidationError(f"{field_name} must contain valid JSON.")

def _read_pdf_labeler_file_request():
    upload = request.files.get("file")
    if upload is None:
        raise DashboardAPIValidationError("Choose a PDF file.")
    content = upload.read()
    if not content.startswith(b"%PDF-"):
        raise DashboardAPIValidationError("The uploaded file must be a PDF.")
    return upload.filename or "document.pdf", content, request.form

def _labeler_ai_auth_check():
    return bool(os.environ.get("OPENAI_API_KEY"))

def _ai_auth_fail(request_id):
    return jsonify_with_status({"success": False, "request_id": request_id,
        "error": {"type": "unavailable", "message": "AI drafting is not configured."}}, 503)

@app.post("/pdf-labeler/api/accessibility-inspect")
def inspect():
    from workshop.pdf_accessibility import inspect_pdf_accessibility
    def build():
        with _uploaded_pdf_path() as (_, path, __):
            return inspect_pdf_accessibility(path)
    return _accessibility_json_response(str(uuid.uuid4()), build)

ACCESSIBILITY_REMEDIATION_ACTIONS = (
    "metadata",
    "catalog_flags",
    "draft_structure",
    "fonts",
    "structure",
    "unicode_map",
    "substitute_fonts",
    "readback_text",
    "field_names",
    "ocr",
    "preserve_pages",
)


def _suffixed_pdf_name(filename: Any, suffix: str) -> str:
    """Append a suffix to a PDF filename without touching an interior ".pdf"."""
    base = re.sub(r"\.pdf$", "", str(filename or "document.pdf"), flags=re.IGNORECASE)
    return f"{base}-{suffix}.pdf"


def _accessibility_json_response(request_id: str, build_data: Any) -> Response:
    """Run one accessibility workshop handler and wrap its result as JSON.

    Every workshop endpoint answers the same way: ``data`` on success, a 400
    for input the person can correct, and a 500 for anything else.
    """
    from workshop.pdf_accessibility import PDFAccessibilityError

    try:
        return jsonify(
            {"success": True, "request_id": request_id, "data": build_data()}
        )
    except DashboardAPIValidationError as exc:
        error_type, message, status = "validation_error", exc.message, exc.status_code
    except (PDFAccessibilityError, json.JSONDecodeError) as exc:
        error_type, message, status = "accessibility_error", str(exc), 400
    except Exception as exc:
        log(f"ALDashboard: accessibility request {request_id} failed: {exc}", "error")
        error_type, message, status = "server_error", "The operation failed. Try a smaller PDF or retry shortly.", 500
    return jsonify_with_status(
        {
            "success": False,
            "request_id": request_id,
            "error": {"type": error_type, "message": message},
        },
        status,
    )


@contextmanager
def _uploaded_pdf_path():
    """Write the uploaded PDF to a temporary file for the duration of a request."""
    filename, content, post_data = _read_pdf_labeler_file_request()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_in:
        tmp_in.write(content)
        input_path = tmp_in.name
    try:
        yield filename, input_path, post_data
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)


def _json_list_of_objects(raw_value: Any, *, field_name: str) -> Optional[List[Dict[str, Any]]]:
    parsed = _parse_optional_json_field(raw_value, field_name=field_name)
    if parsed is None:
        return None
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise DashboardAPIValidationError(f"{field_name} must be a JSON list of objects.")
    return parsed


def _json_object(raw_value: Any, *, field_name: str) -> Dict[str, Any]:
    parsed = _parse_optional_json_field(raw_value, field_name=field_name)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise DashboardAPIValidationError(f"{field_name} must be a JSON object.")
    return parsed


def _run_accessibility_remediation(
    action: str, input_path: str, output_path: str, post_data: Dict[str, Any]
) -> Dict[str, Any]:
    from workshop.pdf_accessibility import (
        apply_manual_structure_repairs,
        apply_pdf_accessibility_settings,
        apply_unicode_map_decisions,
        create_draft_structure_tree,
        embed_fonts_and_rebuild_unicode,
        ocr_image_only_pages,
        repair_duplicate_field_names,
        repair_readback_text,
        substitute_fonts,
    )

    if action in {"metadata", "catalog_flags"}:
        field_order = _parse_optional_json_field(
            post_data.get("field_order"), field_name="field_order"
        )
        if field_order is not None and not isinstance(field_order, list):
            raise DashboardAPIValidationError("field_order must be a JSON list.")
        mark_as_tagged = None
        if action == "catalog_flags" and "marked" in post_data:
            mark_as_tagged = parse_bool(post_data.get("marked"), default=False)
        return apply_pdf_accessibility_settings(
            input_pdf_path=input_path,
            output_pdf_path=output_path,
            field_tooltips={
                str(key): str(value)
                for key, value in _json_object(
                    post_data.get("field_tooltips"), field_name="field_tooltips"
                ).items()
            },
            field_order=[str(value) for value in field_order or []],
            image_alt_text={
                str(key): str(value)
                for key, value in _json_object(
                    post_data.get("image_alt_text"), field_name="image_alt_text"
                ).items()
            },
            metadata=_json_object(post_data.get("metadata"), field_name="metadata"),
            auto_fill_missing_tooltips=False,
            mark_as_tagged=mark_as_tagged,
            repair_declaration=parse_bool(
                post_data.get("repair_declaration"), default=False
            ),
            set_display_doc_title=parse_bool(
                post_data.get("display_doc_title"), default=True
            ),
            set_structure_tab_order=parse_bool(
                post_data.get("set_structure_tab_order"), default=False
            ),
            mark_untagged_as_artifacts=parse_bool(
                post_data.get("mark_untagged_as_artifacts"), default=False
            ),
        )
    if action == "draft_structure":
        heading_decisions = _json_list_of_objects(
            post_data.get("heading_decisions"), field_name="heading_decisions"
        )
        return create_draft_structure_tree(
            input_path,
            output_path,
            overwrite=parse_bool(post_data.get("overwrite"), default=False),
            heading_decisions=heading_decisions,
            content_decisions=_json_list_of_objects(
                post_data.get("content_decisions"), field_name="content_decisions"
            ),
            image_decisions=_json_list_of_objects(
                post_data.get("image_decisions"), field_name="image_decisions"
            ),
            mark_as_tagged=parse_bool(post_data.get("mark_as_tagged"), default=False),
        )
    if action == "ocr":
        return ocr_image_only_pages(
            input_path,
            output_path,
            language=str(post_data.get("language") or "eng")[:12],
        )
    if action == "preserve_pages":
        from workshop.pdf_accessibility_review import preserve_page_tags

        indexes = _parse_optional_json_field(
            post_data.get("page_indexes"), field_name="page_indexes"
        )
        if not isinstance(indexes, list):
            raise DashboardAPIValidationError("page_indexes must be a JSON list.")
        return preserve_page_tags(
            input_path, output_path, indexes,
            deduplicate=parse_bool(post_data.get("deduplicate_field_names"), default=False),
        )
    if action in {"readback_text", "field_names"}:
        repair_call = (
            repair_readback_text if action == "readback_text" else repair_duplicate_field_names
        )
        return repair_call(
            input_path,
            output_path,
            decisions=_json_list_of_objects(
                post_data.get("decisions"), field_name="decisions"
            ),
        )
    if action in {"structure", "unicode_map", "substitute_fonts"}:
        key = "operations" if action == "structure" else "decisions"
        decisions = _json_list_of_objects(post_data.get(key), field_name=key)
        if decisions is None:
            raise DashboardAPIValidationError(f"{key} must be a JSON list of objects.")
        repair = {
            "structure": apply_manual_structure_repairs,
            "unicode_map": apply_unicode_map_decisions,
            "substitute_fonts": substitute_fonts,
        }[action]
        return repair(input_path, output_path, decisions)
    return embed_fonts_and_rebuild_unicode(
        input_path,
        output_path,
        embed_exact_fonts=parse_bool(post_data.get("embed_exact_fonts"), default=True),
        add_unicode_maps=parse_bool(post_data.get("add_unicode_maps"), default=True),
    )


@app.route("/pdf-labeler/api/accessibility-remediate", methods=["POST"])
def pdf_labeler_accessibility_remediate() -> Response:
    """Apply one explicit accessibility repair and return the repaired PDF.

    The accessibility workshop sends its working copy with each request; the
    server keeps nothing between calls.
    """
    request_id = str(uuid.uuid4())

    def build() -> Dict[str, Any]:
        with _uploaded_pdf_path() as (filename, input_path, post_data):
            action = str(post_data.get("action") or "").strip()
            if action not in ACCESSIBILITY_REMEDIATION_ACTIONS:
                raise DashboardAPIValidationError(
                    "action must be one of: "
                    + ", ".join(ACCESSIBILITY_REMEDIATION_ACTIONS)
                    + "."
                )
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_out:
                output_path = tmp_out.name
            try:
                result = _run_accessibility_remediation(
                    action, input_path, output_path, post_data
                )
                with open(output_path, "rb") as output_file:
                    output_bytes = output_file.read()
            finally:
                if os.path.exists(output_path):
                    os.remove(output_path)
        return {
            "filename": _suffixed_pdf_name(filename, "accessible"),
            "pdf_base64": base64.b64encode(output_bytes).decode("ascii"),
            "remediation_result": result,
        }

    return _accessibility_json_response(request_id, build)


@app.route("/pdf-labeler/api/accessibility-font-review", methods=["POST"])
def pdf_labeler_accessibility_font_review() -> Response:
    """Describe unmapped glyphs, with their outlines, for a person to confirm."""
    request_id = str(uuid.uuid4())

    def build() -> Dict[str, Any]:
        from workshop.pdf_accessibility import collect_symbolic_font_review

        with _uploaded_pdf_path() as (_filename, input_path, _post_data):
            return collect_symbolic_font_review(input_path)

    return _accessibility_json_response(request_id, build)


@app.route("/pdf-labeler/api/accessibility-font-substitutes", methods=["POST"])
def pdf_labeler_accessibility_font_substitutes() -> Response:
    """List metric-compatible replacements for fonts with no embedded program."""
    request_id = str(uuid.uuid4())

    def build() -> Dict[str, Any]:
        from workshop.pdf_accessibility import collect_font_substitution_options

        with _uploaded_pdf_path() as (_filename, input_path, _post_data):
            return collect_font_substitution_options(input_path)

    return _accessibility_json_response(request_id, build)


@app.route("/pdf-labeler/api/accessibility-image-previews", methods=["POST"])
def pdf_labeler_accessibility_image_previews() -> Response:
    """Render small PNG previews of page images so a person can judge them.

    Nothing leaves the server here; previews go only to the browser that sent
    the PDF.
    """
    request_id = str(uuid.uuid4())

    def build() -> Dict[str, Any]:
        from workshop.pdf_accessibility import render_image_assets

        with _uploaded_pdf_path() as (_filename, input_path, post_data):
            asset_ids = _parse_optional_json_field(
                post_data.get("asset_ids"), field_name="asset_ids"
            )
            if asset_ids is not None and not isinstance(asset_ids, list):
                raise DashboardAPIValidationError("asset_ids must be a JSON list.")
            previews = render_image_assets(
                input_path, [str(item) for item in asset_ids] if asset_ids else None
            )
        return {
            "previews": {
                asset_id: "data:image/png;base64,"
                + base64.b64encode(png).decode("ascii")
                for asset_id, png in previews.items()
            }
        }

    return _accessibility_json_response(request_id, build)


def _accessibility_ai_model(payload: Dict[str, Any]) -> str:
    return LABELER_DEFAULT_MODEL


def _accessibility_json_list(payload: Dict[str, Any], key: str, limit: int) -> List[Any]:
    items = payload.get(key)
    if not isinstance(items, list):
        raise DashboardAPIValidationError(f"{key} must be a list.")
    if len(items) > limit:
        raise DashboardAPIValidationError(f"At most {limit} {key} may be sent at once.")
    return items


@app.route("/pdf-labeler/api/accessibility-ai-tooltips", methods=["POST"])
def pdf_labeler_accessibility_ai_tooltips() -> Response:
    """Draft accessible field names, only on an explicit authenticated request."""
    request_id = str(uuid.uuid4())
    if not _labeler_ai_auth_check():
        return _ai_auth_fail(request_id)

    def build() -> Dict[str, Any]:
        from workshop.pdf_accessibility import draft_field_tooltips_with_ai

        payload = request.get_json(silent=True) or {}
        fields = _accessibility_json_list(payload, "fields", 500)
        return {
            "tooltips": draft_field_tooltips_with_ai(
                fields, model=_accessibility_ai_model(payload)
            ),
            "review_required": True,
        }

    return _accessibility_json_response(request_id, build)


@app.route("/pdf-labeler/api/accessibility-ai-image-alt", methods=["POST"])
def pdf_labeler_accessibility_ai_image_alt() -> Response:
    """Describe page images with a vision model, only when explicitly asked.

    The pixels leave the server on this request and on no other.
    """
    request_id = str(uuid.uuid4())
    if not _labeler_ai_auth_check():
        return _ai_auth_fail(request_id)

    def build() -> Dict[str, Any]:
        from workshop.pdf_accessibility import describe_images_with_ai, render_image_assets

        with _uploaded_pdf_path() as (filename, input_path, post_data):
            asset_ids = _parse_optional_json_field(
                post_data.get("asset_ids"), field_name="asset_ids"
            )
            if asset_ids is not None and not isinstance(asset_ids, list):
                raise DashboardAPIValidationError("asset_ids must be a JSON list.")
            previews = render_image_assets(
                input_path, [str(item) for item in asset_ids] if asset_ids else None
            )
            descriptions = describe_images_with_ai(
                previews,
                context={"filename": filename},
                model=_accessibility_ai_model(post_data),
            )
        return {
            "descriptions": descriptions,
            "images_examined": len(previews),
            "review_required": True,
        }

    return _accessibility_json_response(request_id, build)


@app.route("/pdf-labeler/api/accessibility-ai-headings", methods=["POST"])
def pdf_labeler_accessibility_ai_headings() -> Response:
    """Draft heading decisions, only on an explicit authenticated request."""
    request_id = str(uuid.uuid4())
    if not _labeler_ai_auth_check():
        return _ai_auth_fail(request_id)

    def build() -> Dict[str, Any]:
        from workshop.pdf_accessibility import draft_heading_levels_with_ai

        payload = request.get_json(silent=True) or {}
        candidates = _accessibility_json_list(payload, "candidates", 500)
        return {
            "decisions": draft_heading_levels_with_ai(
                candidates, model=_accessibility_ai_model(payload)
            ),
            "review_required": True,
        }

    return _accessibility_json_response(request_id, build)


@app.route("/pdf-labeler/api/accessibility-ai-review", methods=["POST"])
def pdf_labeler_accessibility_ai_review() -> Response:
    """Give an advisory second opinion on the workshop's reviewed choices.

    Findings never pass, fail, or certify anything.
    """
    request_id = str(uuid.uuid4())
    if not _labeler_ai_auth_check():
        return _ai_auth_fail(request_id)

    def build() -> Dict[str, Any]:
        from workshop.pdf_accessibility import review_pdf_accessibility_with_ai

        payload = request.get_json(silent=True) or {}
        context = payload.get("context")
        if not isinstance(context, dict):
            raise DashboardAPIValidationError("context must be an object.")
        return {
            "findings": review_pdf_accessibility_with_ai(
                context, model=_accessibility_ai_model(payload)
            ),
            "review_required": True,
        }

    return _accessibility_json_response(request_id, build)

