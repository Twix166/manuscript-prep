from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import run_cli


pytestmark = pytest.mark.smoke


def test_supported_cli_flow_end_to_end(tmp_path: Path, sample_pdf: Path, test_env: dict[str, str]) -> None:
    workdir = tmp_path / "work"
    out_dir = tmp_path / "out" / "treasure_island"
    merged_dir = tmp_path / "merged" / "treasure_island"
    resolved_dir = tmp_path / "resolved" / "treasure_island"
    report_path = tmp_path / "reports" / "treasure_island_report.pdf"

    ingest = run_cli(
        [
            "manuscriptprep_ingest.py",
            "--input",
            str(sample_pdf),
            "--workdir",
            str(workdir),
            "--title",
            "Treasure Island",
            "--chunk-words",
            "20",
            "--min-chunk-words",
            "5",
            "--max-chunk-words",
            "30",
        ],
        env=test_env,
    )
    assert ingest.returncode == 0, ingest.stderr

    orchestrate = run_cli(
        [
            "manuscriptprep_orchestrator_tui_refactored.py",
            "--input-dir",
            str(workdir / "chunks" / "treasure_island"),
            "--output-dir",
            str(out_dir),
            "--no-tui",
        ],
        env=test_env,
    )
    assert orchestrate.returncode == 0, orchestrate.stderr

    merge = run_cli(
        [
            "manuscriptprep_merger.py",
            "--input-dir",
            str(out_dir),
            "--output-dir",
            str(merged_dir),
            "--chunk-manifest",
            str(workdir / "manifests" / "treasure_island" / "chunk_manifest.json"),
        ],
        env=test_env,
    )
    assert merge.returncode == 0, merge.stderr

    resolve = run_cli(
        [
            "manuscriptprep_resolver.py",
            "--input-dir",
            str(merged_dir),
            "--output-dir",
            str(resolved_dir),
            "--model",
            "manuscriptprep-resolver",
        ],
        env=test_env,
    )
    assert resolve.returncode == 0, resolve.stderr

    report = run_cli(
        [
            "manuscriptprep_pdf_report.py",
            "--input-dir",
            str(merged_dir),
            "--output",
            str(report_path),
            "--title",
            "Treasure Island",
        ],
        env=test_env,
    )
    assert report.returncode == 0, report.stderr

    assert (merged_dir / "book_merged.json").exists()
    assert (resolved_dir / "book_resolved.json").exists()
    assert report_path.exists()
    resolved = json.loads((resolved_dir / "book_resolved.json").read_text(encoding="utf-8"))
    assert "characters_resolved" in resolved["entities"]
