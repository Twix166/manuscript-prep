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
    assert b"Active Manuscript" in body
    assert b"DOCX, EPUB, ODT, MOBI, AZW, AZW3, or TXT" in body
    assert b"pipeline-manuscript-select" in body
    assert b"Import Archive" in body


def test_get_web_asset_serves_javascript() -> None:
    content_type, body = get_web_asset("ui/app.js")

    assert content_type.startswith("application/javascript")
    assert b"triggerPipeline" in body
    assert b"Delete Data" in body
    assert b"Archive" in body
    assert b"Merged Analysis" in body
    assert b"Resolved Analysis" in body
    assert b"report_pdf" in body
    assert b"Resolution Progress" in body
    assert b"openStageLogs" in body
    assert b"Readable View" in body


def test_get_web_asset_serves_ingest_results_page() -> None:
    content_type, body = get_web_asset("ui/ingest-results.html")

    assert content_type.startswith("text/html")
    assert b"Ingest Results" in body
