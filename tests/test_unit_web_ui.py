from __future__ import annotations

import pytest

from manuscriptprep.web_ui import get_web_asset


pytestmark = pytest.mark.unit


def test_get_web_asset_serves_index() -> None:
    content_type, body = get_web_asset("ui")

    assert content_type.startswith("text/html")
    assert b"ManuscriptPrep Pipeline Studio" in body
    assert b"Welcome back" in body
    assert b"Create Account" in body
    assert b"Set the admin password" in body
    assert b"Open Admin Interface" in body
    assert b"analysis-detail-modal" in body


def test_get_web_asset_serves_javascript() -> None:
    content_type, body = get_web_asset("ui/app.js")

    assert content_type.startswith("application/javascript")
    assert b"triggerPipeline" in body


def test_get_web_asset_serves_ingest_results_page() -> None:
    content_type, body = get_web_asset("ui/ingest-results.html")

    assert content_type.startswith("text/html")
    assert b"Ingest Results" in body
