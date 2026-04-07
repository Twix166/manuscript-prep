from __future__ import annotations

import pytest

from manuscriptprep.web_ui import get_web_asset


pytestmark = pytest.mark.unit


def test_get_web_asset_serves_index() -> None:
    content_type, body = get_web_asset("ui")

    assert content_type.startswith("text/html")
    assert b"ManuscriptPrep Control Plane" in body


def test_get_web_asset_serves_javascript() -> None:
    content_type, body = get_web_asset("ui/app.js")

    assert content_type.startswith("application/javascript")
    assert b"refreshAll" in body
