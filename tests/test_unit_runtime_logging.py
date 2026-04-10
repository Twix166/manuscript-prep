from __future__ import annotations

import json

import pytest

from manuscriptprep.runtime_logging import emit_runtime_event


pytestmark = pytest.mark.unit


def test_emit_runtime_event_returns_json_line(capsys: pytest.CaptureFixture[str]) -> None:
    line = emit_runtime_event("gateway-api", "startup", port=8765, auth_required=True)
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured)

    assert captured == line
    assert payload["service"] == "gateway-api"
    assert payload["event"] == "startup"
    assert payload["port"] == 8765
    assert payload["auth_required"] is True
