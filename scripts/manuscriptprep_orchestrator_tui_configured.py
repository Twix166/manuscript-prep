#!/usr/bin/env python3
"""Config-aware ManuscriptPrep orchestrator TUI scaffold.

Status:
- Scaffold only.
- Not the supported production orchestrator for this repository.
- Prefer `manuscriptprep_orchestrator_tui_refactored.py`.

Important:
- This is a clean refactor scaffold for wiring your existing orchestrator to the
  shared config system.
- Replace the TODO sections with your current stage execution / TUI logic.
- The goal is to show how config should flow through the orchestrator cleanly.

What this script demonstrates:
- `--config` support
- central path/model/timeout lookup
- environment-free defaults
- JSONL logging
- derived per-book directories
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from manuscriptprep.config import ManuscriptPrepConfig, load_config
from manuscriptprep.logging_utils import setup_logger
from manuscriptprep.paths import PathSet, build_paths, ensure_common_dirs


@dataclass
class OrchestratorSettings:
    structure_model: str
    dialogue_model: str
    entities_model: str
    dossiers_model: str
    idle_seconds: int
    hard_seconds: int
    retries: int
    idle_timeout_backoff: float
    max_idle_timeout_seconds: int
    log_level: str
    log_console: bool


def build_settings(cfg: ManuscriptPrepConfig) -> OrchestratorSettings:
    return OrchestratorSettings(
        structure_model=cfg.require("models", "structure"),
        dialogue_model=cfg.require("models", "dialogue"),
        entities_model=cfg.require("models", "entities"),
        dossiers_model=cfg.require("models", "dossiers"),
        idle_seconds=int(cfg.require("timeouts", "idle_seconds")),
        hard_seconds=int(cfg.require("timeouts", "hard_seconds")),
        retries=int(cfg.get("timeouts", "retries", default=2)),
        idle_timeout_backoff=float(cfg.get("timeouts", "idle_timeout_backoff", default=1.5)),
        max_idle_timeout_seconds=int(cfg.get("timeouts", "max_idle_timeout_seconds", default=600)),
        log_level=str(cfg.get("logging", "level", default="INFO")),
        log_console=bool(cfg.get("logging", "console", default=True)),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ManuscriptPrep chunk passes with shared config.")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument("--book-slug", required=True, help="Book slug directory under chunks_root")
    parser.add_argument("--chunks-dir", default=None, help="Override chunk directory instead of config paths")
    parser.add_argument("--output-dir", default=None, help="Override output directory instead of config paths")
    parser.add_argument("--limit", type=int, default=None, help="Optional limit on chunks to process")
    parser.add_argument("--start-at", default=None, help="Optional chunk filename/id to start at")
    return parser.parse_args()


def discover_chunks(chunks_dir: Path) -> List[Path]:
    chunks = sorted(p for p in chunks_dir.iterdir() if p.is_file() and p.suffix in {".txt", ".md"})
    return chunks


def maybe_slice_chunks(chunks: List[Path], start_at: Optional[str], limit: Optional[int]) -> List[Path]:
    if start_at:
        matched = False
        sliced: List[Path] = []
        for chunk in chunks:
            if chunk.name == start_at or chunk.stem == start_at:
                matched = True
            if matched:
                sliced.append(chunk)
        chunks = sliced
    if limit is not None:
        chunks = chunks[:limit]
    return chunks


def compute_chunk_output_dir(output_root: Path, chunk_file: Path) -> Path:
    return output_root / chunk_file.stem


def stage_model_name(stage: str, settings: OrchestratorSettings) -> str:
    return {
        "structure": settings.structure_model,
        "dialogue": settings.dialogue_model,
        "entities": settings.entities_model,
        "dossiers": settings.dossiers_model,
    }[stage]


def stage_timeout_for_attempt(base_idle: int, backoff: float, max_idle: int, attempt_index: int) -> int:
    timeout = float(base_idle)
    for _ in range(attempt_index):
        timeout *= backoff
    return min(int(round(timeout)), max_idle)


def run_ollama_stage(
    model: str,
    input_text: str,
    idle_seconds: int,
    hard_seconds: int,
) -> Dict[str, Any]:
    """Minimal subprocess wrapper.

    Replace this with your existing streaming + idle-timeout + TUI-aware runner.
    """
    started = time.time()
    proc = subprocess.run(
        ["ollama", "run", model],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=hard_seconds,
    )
    duration = time.time() - started
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "duration_seconds": round(duration, 3),
        "idle_seconds_used": idle_seconds,
    }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    raw_text = raw_text.strip()
    try:
        return json.loads(raw_text)
    except Exception:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(raw_text[start:end + 1])

    raise ValueError("Could not extract JSON object from model output")


def process_stage(
    stage: str,
    chunk_file: Path,
    chunk_output_dir: Path,
    settings: OrchestratorSettings,
    logger,
) -> Dict[str, Any]:
    model = stage_model_name(stage, settings)
    input_text = chunk_file.read_text(encoding="utf-8")

    last_error: Optional[str] = None
    attempts: List[Dict[str, Any]] = []

    for attempt in range(settings.retries + 1):
        idle_seconds = stage_timeout_for_attempt(
            settings.idle_seconds,
            settings.idle_timeout_backoff,
            settings.max_idle_timeout_seconds,
            attempt,
        )

        logger.info(
            f"Running {stage} for {chunk_file.name}",
            extra={"event": {
                "event_type": "stage_start",
                "stage": stage,
                "chunk": chunk_file.stem,
                "model": model,
                "attempt": attempt + 1,
                "idle_seconds": idle_seconds,
                "hard_seconds": settings.hard_seconds,
            }},
        )

        try:
            result = run_ollama_stage(
                model=model,
                input_text=input_text,
                idle_seconds=idle_seconds,
                hard_seconds=settings.hard_seconds,
            )
            attempts.append(result)

            raw_path = chunk_output_dir / f"{stage}.raw.txt"
            write_text(raw_path, result["stdout"])

            if result["returncode"] != 0:
                last_error = result["stderr"] or f"ollama returned {result['returncode']}"
                continue

            parsed = extract_json_object(result["stdout"])
            write_json(chunk_output_dir / f"{stage}.json", parsed)
            return {
                "ok": True,
                "attempts": attempts,
                "parsed_path": str(chunk_output_dir / f"{stage}.json"),
            }

        except subprocess.TimeoutExpired:
            last_error = f"hard timeout exceeded ({settings.hard_seconds}s)"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)

        logger.info(
            f"{stage} failed for {chunk_file.name}",
            extra={"event": {
                "event_type": "stage_retry",
                "stage": stage,
                "chunk": chunk_file.stem,
                "attempt": attempt + 1,
                "error": last_error,
            }},
        )

    write_text(chunk_output_dir / f"{stage}.error.txt", last_error or "unknown error")
    return {
        "ok": False,
        "attempts": attempts,
        "error": last_error,
    }


def run_book(
    chunks_dir: Path,
    output_dir: Path,
    settings: OrchestratorSettings,
    logger,
    start_at: Optional[str],
    limit: Optional[int],
) -> None:
    chunks = maybe_slice_chunks(discover_chunks(chunks_dir), start_at, limit)

    logger.info(
        f"Starting book run for {chunks_dir.name}",
        extra={"event": {
            "event_type": "book_start",
            "book_slug": chunks_dir.name,
            "chunks_dir": str(chunks_dir),
            "output_dir": str(output_dir),
            "chunk_count": len(chunks),
        }},
    )

    for chunk in chunks:
        chunk_output_dir = compute_chunk_output_dir(output_dir, chunk)
        chunk_output_dir.mkdir(parents=True, exist_ok=True)

        stage_summaries: Dict[str, Any] = {}
        chunk_started = time.time()

        for stage in ["structure", "dialogue", "entities", "dossiers"]:
            stage_summaries[stage] = process_stage(stage, chunk, chunk_output_dir, settings, logger)

        timing = {
            "chunk": chunk.stem,
            "total_duration_seconds": round(time.time() - chunk_started, 3),
            "stages": {
                stage: {
                    "ok": summary["ok"],
                    "attempt_count": len(summary.get("attempts", [])),
                    "durations": [a.get("duration_seconds") for a in summary.get("attempts", [])],
                }
                for stage, summary in stage_summaries.items()
            },
        }
        write_json(chunk_output_dir / "timing.json", timing)

        logger.info(
            f"Completed chunk {chunk.name}",
            extra={"event": {
                "event_type": "chunk_complete",
                "chunk": chunk.stem,
                "output_dir": str(chunk_output_dir),
                "timing": timing,
            }},
        )

    logger.info(
        f"Finished book run for {chunks_dir.name}",
        extra={"event": {
            "event_type": "book_complete",
            "book_slug": chunks_dir.name,
            "output_dir": str(output_dir),
        }},
    )


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    settings = build_settings(cfg)
    paths = build_paths(cfg)
    ensure_common_dirs(paths)

    chunks_dir = Path(args.chunks_dir).expanduser() if args.chunks_dir else paths.chunks_root / args.book_slug
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else paths.output_root / args.book_slug
    output_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logger(
        name="manuscriptprep.orchestrator",
        log_path=paths.logs_root / "orchestrator.log.jsonl",
        level=settings.log_level,
        console=settings.log_console,
    )

    logger.info(
        "Loaded config",
        extra={"event": {
            "event_type": "config_loaded",
            "config_path": str(cfg.path),
            "book_slug": args.book_slug,
            "chunks_dir": str(chunks_dir),
            "output_dir": str(output_dir),
            "models": {
                "structure": settings.structure_model,
                "dialogue": settings.dialogue_model,
                "entities": settings.entities_model,
                "dossiers": settings.dossiers_model,
            },
            "timeouts": {
                "idle_seconds": settings.idle_seconds,
                "hard_seconds": settings.hard_seconds,
                "retries": settings.retries,
                "idle_timeout_backoff": settings.idle_timeout_backoff,
                "max_idle_timeout_seconds": settings.max_idle_timeout_seconds,
            },
        }},
    )

    if not chunks_dir.exists():
        raise SystemExit(f"Chunks directory does not exist: {chunks_dir}")

    run_book(
        chunks_dir=chunks_dir,
        output_dir=output_dir,
        settings=settings,
        logger=logger,
        start_at=args.start_at,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
