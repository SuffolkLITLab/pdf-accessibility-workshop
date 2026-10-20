"""Atomic usage counters; no document content or raw IP addresses are stored."""

from contextvars import ContextVar
import hashlib
import hmac
import ipaddress
import os
import secrets
import sqlite3
import time

client = ContextVar("usage_client", default="local")


class UsageError(Exception):
    def __init__(self, message, retry_after=60, status=429):
        super().__init__(message)
        self.retry_after, self.status = retry_after, status


def enabled():
    return (
        os.environ.get(
            "WORKSHOP_LIMITS_ENABLED", "1" if os.environ.get("FLY_APP_NAME") else "0"
        )
        == "1"
    )


def normalize_client(value):
    try:
        address = ipaddress.ip_address(value)
        return (
            str(ipaddress.ip_network(str(address) + "/64", strict=False))
            if address.version == 6
            else str(address)
        )
    except ValueError:
        return "unknown"


def reserve(kind, identity=None, now=None):
    if not enabled():
        return
    now = int(time.time() if now is None else now)
    path = os.environ.get("WORKSHOP_USAGE_DB", "/tmp/workshop-usage.sqlite3")
    try:
        with sqlite3.connect(path, timeout=5) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS counters (scope TEXT, bucket INTEGER, count INTEGER, expires INTEGER, PRIMARY KEY(scope,bucket))"
            )
            db.execute(
                "INSERT OR IGNORE INTO metadata VALUES (?,?)",
                ("salt", secrets.token_hex(32)),
            )
            db.commit()
            salt = db.execute(
                "SELECT value FROM metadata WHERE name='salt'"
            ).fetchone()[0]
            key = hmac.new(
                salt.encode(), (identity or client.get()).encode(), hashlib.sha256
            ).hexdigest()
            limits = (
                [
                    (
                        "api:" + key,
                        60,
                        int(os.environ.get("API_REQUESTS_PER_MINUTE", "60")),
                    )
                ]
                if kind == "api"
                else [
                    (
                        "ai-hour:" + key,
                        3600,
                        int(os.environ.get("AI_CALLS_PER_CLIENT_HOUR", "6")),
                    ),
                    (
                        "ai-day:" + key,
                        86400,
                        int(os.environ.get("AI_CALLS_PER_CLIENT_DAY", "12")),
                    ),
                    ("ai-global", 86400, int(os.environ.get("AI_CALLS_PER_DAY", "40"))),
                ]
            )
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM counters WHERE expires < ?", (now - 86400,))
            for scope, duration, maximum in limits:
                bucket = now // duration
                row = db.execute(
                    "SELECT count FROM counters WHERE scope=? AND bucket=?",
                    (scope, bucket),
                ).fetchone()
                if (row[0] if row else 0) >= maximum:
                    wait = (bucket + 1) * duration - now
                    raise UsageError(
                        (
                            "AI drafting has reached its usage allowance. You can continue reviewing and editing manually."
                            if kind == "ai"
                            else "Too many requests. Please wait a minute and retry; your review is saved."
                        ),
                        wait,
                    )
            for scope, duration, _ in limits:
                bucket = now // duration
                db.execute(
                    "INSERT INTO counters VALUES (?,?,1,?) ON CONFLICT(scope,bucket) DO UPDATE SET count=count+1",
                    (scope, bucket, (bucket + 1) * duration),
                )
    except sqlite3.Error:
        if kind == "api":
            return
        raise UsageError(
            "Usage tracking is temporarily unavailable. Please retry shortly.", 60, 503
        ) from None


def bound_messages(messages):
    text_bytes, image_bytes, images = 0, 0, 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            text_bytes += len(content.encode())
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    text_bytes += len(part.get("text", "").encode())
                elif part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if not url.startswith("data:image/"):
                        raise UsageError(
                            "AI images must be bounded document previews.", status=400
                        )
                    images += 1
                    image_bytes += len(url)
                else:
                    raise UsageError("Unsupported AI input.", status=400)
        else:
            raise UsageError("Unsupported AI input.", status=400)
    if text_bytes > 100000 or images > 4 or image_bytes > 4000000:
        raise UsageError(
            "This AI request is too large. Use a smaller document or fewer selected items.",
            status=400,
        )
