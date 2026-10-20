"""Unified stateless document APIs; browser IndexedDB owns resumable projects."""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import secrets
import threading
import time
from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename
from workshop.office.package import Conflict, PackageError
from workshop.office.repairs import plan_repairs, apply_repairs
from workshop.services import inspect_document, export_bundle
from workshop.validation import validate_pdf

api = Blueprint("documents", __name__, url_prefix="/api/documents")
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="validator")
jobs = {}
job_lock = threading.Lock()


def uploaded():
    file = request.files.get("file")
    if file is None:
        raise PackageError("Choose a PDF, DOCX, or PPTX file.")
    data = file.read()
    if len(data) > 30 * 1024 * 1024:
        raise PackageError("Choose a file smaller than 30 MB.")
    # Logical filename is independent from physical temporary storage.
    filename = (file.filename or "document").replace("\\", "/").split("/")[-1][:250]
    return data, filename


def json_field(name, default=None):
    value = request.form.get(name)
    if value is None:
        return default
    try:
        return json.loads(value)
    except ValueError:
        raise PackageError(f"{name} must be valid JSON.")


@api.errorhandler(PackageError)
def invalid(error):
    return jsonify(
        success=False,
        error={
            "message": str(error),
            "type": "conflict" if isinstance(error, Conflict) else "validation_error",
        },
    ), (409 if isinstance(error, Conflict) else 400)


@api.post("/inspect")
def inspect():
    source, name = uploaded()
    return jsonify(success=True, data=inspect_document(source, name))


@api.post("/plan")
def plan():
    source, name = uploaded()
    return jsonify(
        success=True,
        data=plan_repairs(
            source,
            name,
            request.form.get("expected_sha256"),
            json_field("decisions"),
            request.form.get("idempotency_key"),
        ),
    )


@api.post("/apply")
def apply():
    source, _ = uploaded()
    plan = json_field("plan")
    result, report, receipt = apply_repairs(source, plan)
    return jsonify(
        success=True,
        data={
            "document_base64": base64.b64encode(result).decode(),
            "inspection": report,
            "receipt": receipt,
        },
    )


@api.post("/export")
def export():
    source, name = uploaded()
    evidence = json_field("evidence", {})
    if not isinstance(evidence, dict):
        raise PackageError("Evidence must be an object.")
    bundle = export_bundle(source, name, evidence)
    return jsonify(
        success=True,
        data={
            "filename": (secure_filename(name).rsplit(".", 1)[0] or "document")
            + "-review.zip",
            "bundle_base64": base64.b64encode(bundle).decode(),
        },
    )


@api.post("/validate")
def validate():
    source, _ = uploaded()
    if not source.startswith(b"%PDF-"):
        raise PackageError(
            "Independent PDF/UA validation requires actual PDF bytes. Native Office review does not transfer to PDF exports."
        )
    now = time.monotonic()
    with job_lock:
        for key in list(jobs):
            if jobs[key]["expires"] < now and jobs[key]["future"].done():
                del jobs[key]
        if len(jobs) >= 12:
            return (
                jsonify(
                    success=False,
                    error={"message": "Validation capacity is full. Retry later."},
                ),
                429,
            )
        token = secrets.token_urlsafe(32)
        job_id = secrets.token_urlsafe(18)
        future = executor.submit(
            validate_pdf, source, request.form.get("profile", "ua1")
        )
        jobs[job_id] = {"token": token, "future": future, "expires": now + 1800}
    return (
        jsonify(
            success=True,
            data={"id": job_id, "token": token, "status": "queued", "expires_in": 1800},
        ),
        202,
    )


@api.get("/validation/<job_id>")
def validation_result(job_id):
    with job_lock:
        job = jobs.get(job_id)
        if (
            not job
            or job["expires"] < time.monotonic()
            or not secrets.compare_digest(
                request.headers.get("Authorization", ""), "Bearer " + job["token"]
            )
        ):
            return (
                jsonify(
                    success=False,
                    error={"message": "Validation job unavailable or expired."},
                ),
                404,
            )
        future = job["future"]
    if not future.done():
        return jsonify(success=True, data={"status": "running"})
    try:
        result = future.result()
    except Exception:
        result = {
            "outcome": "error",
            "detail": "Validation worker failed; no conformance result was inferred.",
        }
    return jsonify(success=True, data={"status": "complete", "result": result})


@api.post("preview")
def preview():
    from workshop.office.preview import convert

    source, name = uploaded()
    return jsonify(
        success=True, data=convert(source, name, request.form.get("expected_sha256"))
    )


@api.post("ai-drafts")
def ai_drafts():
    from workshop.office.ai_drafts import draft_repairs

    source, name = uploaded()
    return jsonify(
        success=True,
        data=draft_repairs(source, name, request.form.get("expected_sha256")),
    )
