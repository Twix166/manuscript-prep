from __future__ import annotations

import argparse
import json
from pathlib import Path

from manuscriptprep.config import load_config
from manuscriptprep.paths import build_paths
from manuscriptprep_pdf_report import load_report_data, resolve_report_settings


def test_report_settings_prefer_resolved_dir_when_book_resolved_exists(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    resolved_dir = workspace_root / "resolved" / "treasure_island"
    merged_dir = workspace_root / "merged" / "treasure_island"
    resolved_dir.mkdir(parents=True)
    merged_dir.mkdir(parents=True)
    (resolved_dir / "book_resolved.json").write_text(json.dumps({"book_slug": "treasure_island"}), encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: manuscriptprep",
                "paths:",
                f"  repo_root: {tmp_path}",
                f"  workspace_root: {workspace_root}",
                f"  input_root: {workspace_root / 'input'}",
                f"  extracted_root: {workspace_root / 'extracted'}",
                f"  cleaned_root: {workspace_root / 'cleaned'}",
                f"  chunks_root: {workspace_root / 'chunks'}",
                f"  output_root: {workspace_root / 'out'}",
                f"  merged_root: {workspace_root / 'merged'}",
                f"  resolved_root: {workspace_root / 'resolved'}",
                f"  reports_root: {workspace_root / 'reports'}",
                f"  logs_root: {workspace_root / 'logs'}",
                "models:",
                "  structure: manuscriptprep-structure",
                "  dialogue: manuscriptprep-dialogue",
                "  entities: manuscriptprep-entities",
                "  dossiers: manuscriptprep-dossiers",
                "  resolver: manuscriptprep-resolver",
                "timeouts:",
                "  idle_seconds: 10",
                "  hard_seconds: 30",
                "  retries: 0",
                "  idle_timeout_backoff: 1.5",
                "  max_idle_timeout_seconds: 30",
                "  resolver_timeout_seconds: 30",
                "chunking:",
                "  target_words: 20",
                "  min_words: 5",
                "  max_words: 30",
                "logging:",
                "  level: INFO",
                "  jsonl: true",
                "  console: false",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_config(config_path)
    settings = resolve_report_settings(
        argparse.Namespace(
            config=config_path,
            book_slug="treasure_island",
            input_dir=None,
            output=None,
            title=None,
            subtitle="Merged ManuscriptPrep Analysis Report",
        ),
        cfg,
    )

    assert settings.input_dir == resolved_dir
    assert settings.source_mode == "resolved"
    assert settings.output_path == build_paths(cfg).reports_root / "treasure_island_report.pdf"


def test_load_report_data_uses_resolved_book_and_resolution_report(tmp_path: Path) -> None:
    resolved_dir = tmp_path / "resolved" / "treasure_island"
    merged_dir = tmp_path / "merged" / "treasure_island"
    resolved_dir.mkdir(parents=True)
    merged_dir.mkdir(parents=True)

    (resolved_dir / "book_resolved.json").write_text(
        json.dumps(
            {
                "book_slug": "treasure_island",
                "book_title": "Treasure Island Resolved",
                "structure": {"chapters": ["CHAPTER I"]},
                "dialogue": {"dominant_pov": "third_person"},
                "entities": {"characters": ["Jim"]},
                "dossiers": {"character_dossiers": []},
            }
        ),
        encoding="utf-8",
    )
    (resolved_dir / "resolution_report.json").write_text(
        json.dumps({"model": "manuscriptprep-resolver", "group_count": 2}),
        encoding="utf-8",
    )
    (merged_dir / "merge_report.json").write_text(
        json.dumps({"chunk_count": 62, "present_counts": {}, "missing": {}}),
        encoding="utf-8",
    )
    (merged_dir / "conflict_report.json").write_text(json.dumps({"summary": {}}), encoding="utf-8")

    data = load_report_data(resolved_dir)

    assert data["source_mode"]["mode"] == "resolved"
    assert data["book"]["book_title"] == "Treasure Island Resolved"
    assert data["structure"]["chapters"] == ["CHAPTER I"]
    assert data["resolution_report"]["model"] == "manuscriptprep-resolver"
    assert data["merge_report"]["chunk_count"] == 62
