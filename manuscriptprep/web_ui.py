"""Helpers for serving the minimal gateway web UI."""

from __future__ import annotations

from pathlib import Path


WEB_UI_ROOT = Path(__file__).resolve().parents[1] / "webui"


def get_web_asset(path: str) -> tuple[str, bytes]:
    normalized = path.strip("/") or "index.html"
    if normalized == "ui":
        normalized = "index.html"
    if normalized == "ui/":
        normalized = "index.html"
    if normalized.startswith("ui/"):
        normalized = normalized.removeprefix("ui/")

    full_path = WEB_UI_ROOT / normalized
    if not full_path.exists() or not full_path.is_file():
        raise FileNotFoundError(normalized)

    suffix = full_path.suffix.lower()
    content_type = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
    }.get(suffix, "application/octet-stream")
    return content_type, full_path.read_bytes()
