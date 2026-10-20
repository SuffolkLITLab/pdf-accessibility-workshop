"""Run with: gunicorn web.app:app"""

import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .routes import app as api

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web/static"
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
app.config.update(WORKSHOP_STANDALONE=True, MAX_CONTENT_LENGTH=32 * 1024 * 1024,
                  MAX_FORM_MEMORY_SIZE=8 * 1024 * 1024)
app.register_blueprint(api)


@app.get("/")
@app.get("/review/<uuid:review_id>")
def index(review_id=None):
    return render_template("index.html", config={
        "aiEnabled": bool(os.environ.get("OPENAI_API_KEY")),
        "model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
    })


@app.get("/healthz")
def health():
    return jsonify(status="ok")


@app.get("/assets/<path:name>")
def assets(name):
    if name not in {
        "pdf_accessibility_workshop.js", "pdf_accessibility_workshop.css",
        "litlabtheme/bootstrap-theme.css", "litlabtheme/variables.css",
        "litlabtheme/custom.css",
    }:
        return "", 404
    return send_from_directory(ASSETS, name)


@app.before_request
def same_origin():
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify(success=False, error={"message": "Cross-origin requests are not allowed."}), 403


@app.after_request
def response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith("/pdf-labeler/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(HTTPException)
def http_error(error):
    return jsonify(success=False, error={"message": error.description}), error.code
