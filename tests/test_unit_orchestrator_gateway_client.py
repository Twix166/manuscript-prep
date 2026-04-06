from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import manuscriptprep_orchestrator_tui_refactored as orchestrator_tui


pytestmark = pytest.mark.unit


def test_run_gateway_plain_submits_orchestrate_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    chunks_dir = tmp_path / "work" / "chunks" / "treasure_island"
    chunks_dir.mkdir(parents=True)
    (chunks_dir / "chunk_000.txt").write_text("Jim spoke to Silver.", encoding="utf-8")
    output_dir = tmp_path / "out" / "treasure_island"

    calls: list[tuple[str, str, str, dict | None]] = []

    def fake_gateway_request(base_url: str, method: str, path: str, payload=None):
        calls.append((base_url, method, path, payload))
        if method == "POST" and path == "/v1/jobs":
            return {"job_id": "job-123", "status": "queued"}
        if method == "POST" and path == "/v1/jobs/job-123/run":
            return {"job_id": "job-123", "status": "succeeded"}
        raise AssertionError(f"Unexpected gateway request: {method} {path}")

    monkeypatch.setattr(orchestrator_tui, "gateway_request", fake_gateway_request)

    args = argparse.Namespace(
        input=None,
        input_dir=chunks_dir,
        output_dir=output_dir,
        config=None,
        book_slug="treasure_island",
        gateway_url="http://gateway.local",
    )
    logger = orchestrator_tui.JsonlLogger(tmp_path / "orchestrator.log.jsonl", "run-123")

    rc = orchestrator_tui.run_gateway_plain(args, output_dir, logger)

    assert rc == 0
    assert calls[0][0] == "http://gateway.local"
    assert calls[0][1] == "POST"
    assert calls[0][2] == "/v1/jobs"
    assert calls[0][3]["pipeline"] == "orchestrate"
    assert calls[0][3]["options"]["input_dir"] == str(chunks_dir)
    assert calls[0][3]["options"]["output_dir"] == str(output_dir)
    assert calls[1][2] == "/v1/jobs/job-123/run"
