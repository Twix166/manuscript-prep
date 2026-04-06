from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers import run_cli


pytestmark = pytest.mark.integration


def test_ingest_cli_creates_expected_workspace_artifacts(tmp_path: Path, sample_pdf: Path, test_env: dict[str, str]) -> None:
    workdir = tmp_path / "work"
    result = run_cli(
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
    assert result.returncode == 0, result.stderr
    assert (workdir / "manifests" / "treasure_island" / "ingest_manifest.json").exists()
    assert (workdir / "chunks" / "treasure_island").exists()


def test_ingest_cli_uses_config_defaults_for_paths_and_chunking(tmp_path: Path, sample_pdf: Path, test_env: dict[str, str]) -> None:
    workspace_root = tmp_path / "workspace"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: manuscriptprep",
                "  environment: test",
                "paths:",
                f"  repo_root: {tmp_path}",
                f"  workspace_root: {workspace_root}",
                f"  input_root: {workspace_root / 'source'}",
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
                "ollama:",
                "  host: http://127.0.0.1:11434",
                "  command: ollama",
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
    result = run_cli(
        [
            "manuscriptprep_ingest.py",
            "--config",
            str(config_path),
            "--input",
            str(sample_pdf),
            "--title",
            "Treasure Island",
        ],
        env=test_env,
    )
    assert result.returncode == 0, result.stderr
    assert (workspace_root / "extracted" / "treasure_island" / "raw.txt").exists()
    assert (workspace_root / "cleaned" / "treasure_island" / "clean.txt").exists()
    assert (workspace_root / "chunks" / "treasure_island").exists()
    ingest_manifest = json.loads((workspace_root / "manifests" / "treasure_island" / "ingest_manifest.json").read_text(encoding="utf-8"))
    assert ingest_manifest["config_path"] == str(config_path.resolve())
    assert ingest_manifest["chunking"]["target_chunk_words"] == 20


def test_orchestrator_cli_with_config_writes_outputs(tmp_path: Path, test_env: dict[str, str]) -> None:
    chunks_dir = tmp_path / "work" / "chunks" / "treasure_island"
    chunks_dir.mkdir(parents=True)
    (chunks_dir / "chunk_000.txt").write_text("Jim spoke to Silver.", encoding="utf-8")
    output_root = tmp_path / "out"
    logs_root = tmp_path / "logs"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "paths:",
                f"  output_root: {output_root}",
                f"  logs_root: {logs_root}",
                "models:",
                "  structure: manuscriptprep-structure",
                "  dialogue: manuscriptprep-dialogue",
                "  entities: manuscriptprep-entities",
                "  dossiers: manuscriptprep-dossiers",
                "ollama:",
                "  command: ollama",
                "timeouts:",
                "  idle_seconds: 10",
                "  hard_seconds: 30",
                "  retries: 0",
                "  idle_timeout_backoff: 1.5",
                "  max_idle_timeout_seconds: 30",
                "logging:",
                "  level: INFO",
                "  console: false",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli(
        [
            "manuscriptprep_orchestrator_tui_refactored.py",
            "--config",
            str(config_path),
            "--input-dir",
            str(chunks_dir),
            "--book-slug",
            "treasure_island",
            "--no-tui",
        ],
        env=test_env,
    )
    assert result.returncode == 0, result.stderr
    chunk_out = output_root / "treasure_island" / "chunk_000"
    assert (chunk_out / "structure.json").exists()
    assert (chunk_out / "dialogue.json").exists()
    assert (chunk_out / "entities.json").exists()
    assert (chunk_out / "dossiers.json").exists()
    assert (chunk_out / "timing.json").exists()
    assert (logs_root / "orchestrator.log.jsonl").exists()
    timing = json.loads((chunk_out / "timing.json").read_text(encoding="utf-8"))
    assert set(timing["passes"]) == {"structure", "dialogue", "entities", "dossiers"}


def test_merger_cli_uses_config_defaults_for_paths(tmp_path: Path, test_env: dict[str, str]) -> None:
    workspace_root = tmp_path / "workspace"
    output_root = workspace_root / "out"
    merged_root = workspace_root / "merged"
    book_slug = "treasure_island"
    chunk_dir = output_root / book_slug / "chunk_000"
    chunk_dir.mkdir(parents=True)
    (chunk_dir / "structure.json").write_text(json.dumps({"chapters": ["CHAPTER I"], "parts": [], "scene_breaks": [], "status": "ok"}) + "\n", encoding="utf-8")
    (chunk_dir / "dialogue.json").write_text(json.dumps({"pov": "third_person", "dialogue": True, "internal_thought": False, "explicitly_attributed_speakers": ["Jim"], "unattributed_dialogue_present": False}) + "\n", encoding="utf-8")
    (chunk_dir / "entities.json").write_text(json.dumps({"characters": ["Jim"], "places": [], "objects": [], "identity_notes": []}) + "\n", encoding="utf-8")
    (chunk_dir / "dossiers.json").write_text(json.dumps({"character_dossiers": [{"name": "Jim", "roles": ["protagonist"], "variants": ["Jim"], "surface_variants": ["Jim"], "chunks": ["chunk_000"]}]}) + "\n", encoding="utf-8")
    (chunk_dir / "timing.json").write_text(json.dumps({"chunk": "chunk_000", "passes": {}, "total_duration_seconds": 1.0}) + "\n", encoding="utf-8")

    manifest_dir = workspace_root / "manifests" / book_slug
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "chunk_manifest.json").write_text(
        json.dumps(
            {
                "book_title": "Treasure Island",
                "chunks": [{"chunk_id": "chunk_000"}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: manuscriptprep",
                "  environment: test",
                "paths:",
                f"  repo_root: {tmp_path}",
                f"  workspace_root: {workspace_root}",
                f"  input_root: {workspace_root / 'source'}",
                f"  extracted_root: {workspace_root / 'extracted'}",
                f"  cleaned_root: {workspace_root / 'cleaned'}",
                f"  chunks_root: {workspace_root / 'chunks'}",
                f"  output_root: {output_root}",
                f"  merged_root: {merged_root}",
                f"  resolved_root: {workspace_root / 'resolved'}",
                f"  reports_root: {workspace_root / 'reports'}",
                f"  logs_root: {workspace_root / 'logs'}",
                "models:",
                "  structure: manuscriptprep-structure",
                "  dialogue: manuscriptprep-dialogue",
                "  entities: manuscriptprep-entities",
                "  dossiers: manuscriptprep-dossiers",
                "  resolver: manuscriptprep-resolver",
                "ollama:",
                "  host: http://127.0.0.1:11434",
                "  command: ollama",
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

    result = run_cli(
        [
            "manuscriptprep_merger.py",
            "--config",
            str(config_path),
            "--book-slug",
            book_slug,
        ],
        env=test_env,
    )
    assert result.returncode == 0, result.stderr
    book_merged = json.loads((merged_root / book_slug / "book_merged.json").read_text(encoding="utf-8"))
    assert book_merged["book_slug"] == book_slug
    assert book_merged["book_title"] == "Treasure Island"
    assert book_merged["config_path"] == str(config_path.resolve())


def test_resolver_cli_uses_config_defaults_for_paths_and_model(tmp_path: Path, test_env: dict[str, str]) -> None:
    workspace_root = tmp_path / "workspace"
    merged_root = workspace_root / "merged"
    resolved_root = workspace_root / "resolved"
    book_slug = "treasure_island"
    merged_dir = merged_root / book_slug
    merged_dir.mkdir(parents=True)

    book_merged = {
        "book_slug": book_slug,
        "book_title": "Treasure Island",
        "dialogue": {"explicitly_attributed_speakers": ["Jim"]},
        "entities": {"characters": ["Jim", "Jim Hawkins"]},
        "dossiers": {"character_dossiers": [{"name": "Jim", "surface_variants": ["Jim", "Jim Hawkins"]}]},
    }
    (merged_dir / "book_merged.json").write_text(json.dumps(book_merged, indent=2) + "\n", encoding="utf-8")
    (merged_dir / "entities_merged.json").write_text(json.dumps({"characters": ["Jim", "Jim Hawkins"], "characters_normalized": []}, indent=2) + "\n", encoding="utf-8")
    (merged_dir / "dossiers_merged.json").write_text(json.dumps({"character_dossiers": [{"name": "Jim", "surface_variants": ["Jim", "Jim Hawkins"]}]}, indent=2) + "\n", encoding="utf-8")
    (merged_dir / "conflict_report.json").write_text(json.dumps({}, indent=2) + "\n", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: manuscriptprep",
                "  environment: test",
                "paths:",
                f"  repo_root: {tmp_path}",
                f"  workspace_root: {workspace_root}",
                f"  input_root: {workspace_root / 'source'}",
                f"  extracted_root: {workspace_root / 'extracted'}",
                f"  cleaned_root: {workspace_root / 'cleaned'}",
                f"  chunks_root: {workspace_root / 'chunks'}",
                f"  output_root: {workspace_root / 'out'}",
                f"  merged_root: {merged_root}",
                f"  resolved_root: {resolved_root}",
                f"  reports_root: {workspace_root / 'reports'}",
                f"  logs_root: {workspace_root / 'logs'}",
                "models:",
                "  structure: manuscriptprep-structure",
                "  dialogue: manuscriptprep-dialogue",
                "  entities: manuscriptprep-entities",
                "  dossiers: manuscriptprep-dossiers",
                "  resolver: manuscriptprep-resolver",
                "ollama:",
                "  host: http://127.0.0.1:11434",
                "  command: ollama",
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

    result = run_cli(
        [
            "manuscriptprep_resolver.py",
            "--config",
            str(config_path),
            "--book-slug",
            book_slug,
        ],
        env=test_env,
    )
    assert result.returncode == 0, result.stderr
    resolution_report = json.loads((resolved_root / book_slug / "resolution_report.json").read_text(encoding="utf-8"))
    book_resolved = json.loads((resolved_root / book_slug / "book_resolved.json").read_text(encoding="utf-8"))
    assert resolution_report["model"] == "manuscriptprep-resolver"
    assert resolution_report["config_path"] == str(config_path.resolve())
    assert book_resolved["config_path"] == str(config_path.resolve())


def test_pdf_report_cli_uses_config_defaults_for_paths(tmp_path: Path, test_env: dict[str, str]) -> None:
    workspace_root = tmp_path / "workspace"
    merged_root = workspace_root / "merged"
    reports_root = workspace_root / "reports"
    book_slug = "treasure_island"
    merged_dir = merged_root / book_slug
    merged_dir.mkdir(parents=True)

    (merged_dir / "book_merged.json").write_text(
        json.dumps({"book_slug": book_slug, "book_title": "Treasure Island"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (merged_dir / "structure_merged.json").write_text(
        json.dumps({"chapters": ["CHAPTER I"], "parts": [], "scene_breaks": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    (merged_dir / "dialogue_merged.json").write_text(
        json.dumps(
            {
                "dominant_pov": "third_person",
                "observed_pov_values": ["third_person"],
                "dialogue_present_in_chunks": 1,
                "internal_thought_present_in_chunks": 0,
                "unattributed_dialogue_present_in_chunks": 0,
                "explicitly_attributed_speakers": ["Jim"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (merged_dir / "entities_merged.json").write_text(
        json.dumps({"characters": ["Jim"], "places": [], "objects": [], "identity_notes": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    (merged_dir / "dossiers_merged.json").write_text(
        json.dumps({"character_dossiers": []}, indent=2) + "\n",
        encoding="utf-8",
    )
    (merged_dir / "conflict_report.json").write_text(
        json.dumps({"summary": {}}, indent=2) + "\n",
        encoding="utf-8",
    )
    (merged_dir / "merge_report.json").write_text(
        json.dumps({"chunk_count": 1, "present_counts": {}, "missing": {}}, indent=2) + "\n",
        encoding="utf-8",
    )

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: manuscriptprep",
                "  environment: test",
                "paths:",
                f"  repo_root: {tmp_path}",
                f"  workspace_root: {workspace_root}",
                f"  input_root: {workspace_root / 'source'}",
                f"  extracted_root: {workspace_root / 'extracted'}",
                f"  cleaned_root: {workspace_root / 'cleaned'}",
                f"  chunks_root: {workspace_root / 'chunks'}",
                f"  output_root: {workspace_root / 'out'}",
                f"  merged_root: {merged_root}",
                f"  resolved_root: {workspace_root / 'resolved'}",
                f"  reports_root: {reports_root}",
                f"  logs_root: {workspace_root / 'logs'}",
                "models:",
                "  structure: manuscriptprep-structure",
                "  dialogue: manuscriptprep-dialogue",
                "  entities: manuscriptprep-entities",
                "  dossiers: manuscriptprep-dossiers",
                "  resolver: manuscriptprep-resolver",
                "ollama:",
                "  host: http://127.0.0.1:11434",
                "  command: ollama",
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

    result = run_cli(
        [
            "manuscriptprep_pdf_report.py",
            "--config",
            str(config_path),
            "--book-slug",
            book_slug,
        ],
        env=test_env,
    )
    assert result.returncode == 0, result.stderr
    assert (reports_root / f"{book_slug}_report.pdf").exists()
