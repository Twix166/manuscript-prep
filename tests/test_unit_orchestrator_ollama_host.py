from __future__ import annotations

import json
from pathlib import Path

import pytest

import manuscriptprep_orchestrator_tui_refactored as orchestrator


pytestmark = pytest.mark.unit


class _FakeResponse:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


def test_run_ollama_streaming_uses_host_when_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["timeout"] = str(timeout)
        body = json.loads(req.data.decode("utf-8"))
        seen["model"] = body["model"]
        return _FakeResponse(
            [
                json.dumps({"response": "{\"ok\":", "done": False}).encode("utf-8"),
                json.dumps({"response": " true}", "done": True}).encode("utf-8"),
            ]
        )

    monkeypatch.setattr(orchestrator.urllib_request, "urlopen", fake_urlopen)
    monkeypatch.setattr(orchestrator.shutil, "which", lambda _cmd: None)

    runtime = orchestrator.RuntimeConfig(ollama_host="http://ollama.test:11434")
    state = orchestrator.TUIState()
    state.pass_started_at = 0.0
    logger = orchestrator.JsonlLogger(tmp_path / "orchestrator.log.jsonl", run_id="test-run")

    output = orchestrator.run_ollama_streaming(
        runtime=runtime,
        model="demo-model",
        prompt_text="hello",
        state=state,
        live=None,
        logger=logger,
        chunk_name="chunk_001",
        pass_name="structure",
        attempt=1,
        idle_timeout=15,
        hard_timeout=30,
    )

    assert output == '{"ok": true}'
    assert seen["url"] == "http://ollama.test:11434/api/generate"
    assert seen["model"] == "demo-model"
    assert seen["timeout"] == "15"
    assert state.model_stdout_lines
