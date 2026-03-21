#!/usr/bin/env python3
"""
manuscriptprep_orchestrator_tui.py

A live TUI orchestrator for a 4-pass Ollama manuscript pipeline.

Passes:
1. structure
2. dialogue
3. entities
4. dossiers

Expected Ollama models:
- manuscriptprep-structure
- manuscriptprep-dialogue
- manuscriptprep-entities
- manuscriptprep-dossiers

Features:
- Rich TUI with live pass/chunk status
- Global structured JSONL log for observability
- Per-chunk error files
- Retry support per pass
- Skip or fail-fast behavior
- Approximate token speed display
- Raw output capture and parsed JSON output

Usage:
    python manuscriptprep_orchestrator_tui.py --input chunk_0.txt --output-dir out
    python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out

Examples:
    python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out
    python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out --retries 1 --on-failure skip
    python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out --on-failure stop
    python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out --no-tui
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


STRUCTURE_MODEL = "manuscriptprep-structure"
DIALOGUE_MODEL = "manuscriptprep-dialogue"
ENTITIES_MODEL = "manuscriptprep-entities"
DOSSIERS_MODEL = "manuscriptprep-dossiers"

PASS_SEQUENCE = [
    ("structure", STRUCTURE_MODEL),
    ("dialogue", DIALOGUE_MODEL),
    ("entities", ENTITIES_MODEL),
    ("dossiers", DOSSIERS_MODEL),
]

# Regexes for a possible real token/s number in output, if present.
TPS_PATTERNS = [
    re.compile(r"(?i)\b(eval(?:uation)?(?:\s+rate)?|tokens?/s|tok/s)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)"),
    re.compile(r"(?i)\b([0-9]+(?:\.[0-9]+)?)\s*(?:tokens?/s|tok/s)\b"),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TUIState:
    current_chunk: str = "-"
    current_pass: str = "-"
    pass_status: str = "idle"
    current_step: str = "-"
    pass_started_at: Optional[float] = None
    chunks_total: int = 0
    chunks_completed: int = 0
    chunks_failed: int = 0
    retries_used: int = 0
    estimated_tps: Optional[float] = None
    real_tps: Optional[float] = None
    stdout_token_count: int = 0
    orchestrator_log: List[str] = field(default_factory=list)
    model_stdout_lines: List[str] = field(default_factory=list)
    model_stderr_lines: List[str] = field(default_factory=list)

    def log(self, msg: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.orchestrator_log.append(f"[{timestamp}] {msg}")
        self.orchestrator_log = self.orchestrator_log[-300:]

    def append_stdout(self, line: str) -> None:
        self.model_stdout_lines.append(line.rstrip("\n"))
        self.model_stdout_lines = self.model_stdout_lines[-500:]

    def append_stderr(self, line: str) -> None:
        self.model_stderr_lines.append(line.rstrip("\n"))
        self.model_stderr_lines = self.model_stderr_lines[-250:]


class JsonlLogger:
    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(
        self,
        *,
        level: str,
        event_type: str,
        message: str,
        chunk: Optional[str] = None,
        pass_name: Optional[str] = None,
        step: Optional[str] = None,
        model: Optional[str] = None,
        attempt: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        record: Dict[str, Any] = {
            "timestamp": utc_now_iso(),
            "level": level.upper(),
            "event_type": event_type,
            "message": message,
            "run_id": self.run_id,
            "chunk": chunk,
            "pass": pass_name,
            "step": step,
            "model": model,
            "attempt": attempt,
            "pid": os.getpid(),
        }
        if extra:
            record.update(extra)

        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a 4-pass manuscript pipeline with a live terminal UI and structured logging."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="Single chunk text file")
    group.add_argument("--input-dir", type=Path, help="Directory containing chunk text files")

    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for outputs")
    parser.add_argument("--ollama-bin", default="ollama", help="Path to ollama binary")
    parser.add_argument("--glob", default="*.txt", help="Glob for input-dir mode")
    parser.add_argument("--no-tui", action="store_true", help="Disable TUI and use plain logging")
    parser.add_argument("--retries", type=int, default=1, help="Retries per pass after first failure")
    parser.add_argument(
        "--on-failure",
        choices=["skip", "stop"],
        default="skip",
        help="Skip failed chunk or stop entire run",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Structured JSONL log file path. Defaults to <output-dir>/orchestrator.log.jsonl",
    )
    return parser.parse_args()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("Model output is not valid JSON")
        snippet = text[start : end + 1]
        return json.loads(snippet)


def collect_inputs(args: argparse.Namespace) -> List[Path]:
    if args.input:
        if not args.input.is_file():
            raise RuntimeError(f"Input file does not exist: {args.input}")
        return [args.input]

    if not args.input_dir.is_dir():
        raise RuntimeError(f"Input directory does not exist: {args.input_dir}")

    files = sorted(args.input_dir.glob(args.glob))
    if not files:
        raise RuntimeError(f"No files matched {args.glob} in {args.input_dir}")
    return files


def build_dossier_input(excerpt_text: str, entities_json: Dict[str, Any], dialogue_json: Dict[str, Any]) -> str:
    payload = {
        "characters": entities_json.get("characters", []),
        "dialogue_info": dialogue_json,
    }
    return (
        "EXCERPT:\n"
        f"{excerpt_text.strip()}\n\n"
        "EXTRACTION_DATA:\n"
        f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n"
    )


def stream_reader(pipe, target_queue: queue.Queue, stream_name: str) -> None:
    try:
        for line in iter(pipe.readline, ""):
            target_queue.put((stream_name, line))
    finally:
        pipe.close()


def approx_token_count(text: str) -> int:
    # Very rough token estimate for live UI only.
    # Good enough operationally; not an exact model token count.
    return len(re.findall(r"\S+", text))


def extract_tps_from_text(text: str) -> Optional[float]:
    for pattern in TPS_PATTERNS:
        m = pattern.search(text)
        if m:
            # Some regexes have 2 groups, some 1.
            for g in reversed(m.groups()):
                try:
                    return float(g)
                except (TypeError, ValueError):
                    continue
    return None


def render_tui(state: TUIState):
    elapsed = "-"
    if state.pass_started_at is not None:
        elapsed = f"{time.time() - state.pass_started_at:.1f}s"

    progress = "-"
    if state.chunks_total > 0:
        progress = f"{state.chunks_completed}/{state.chunks_total} complete, {state.chunks_failed} failed"

    if state.real_tps is not None:
        tps_display = f"{state.real_tps:.1f} tok/s (reported)"
    elif state.estimated_tps is not None:
        tps_display = f"{state.estimated_tps:.1f} tok/s (estimated)"
    else:
        tps_display = "-"

    status_table = Table.grid(expand=True)
    status_table.add_column(ratio=1)
    status_table.add_column(ratio=3)
    status_table.add_row("Chunk", state.current_chunk)
    status_table.add_row("Pass", state.current_pass)
    status_table.add_row("Status", state.pass_status)
    status_table.add_row("Step", state.current_step)
    status_table.add_row("Elapsed", elapsed)
    status_table.add_row("Progress", progress)
    status_table.add_row("Retries", str(state.retries_used))
    status_table.add_row("Token speed", tps_display)

    orchestrator_text = Text("\n".join(state.orchestrator_log[-30:]) or "(no log yet)")
    stdout_text = Text("\n".join(state.model_stdout_lines[-40:]) or "(no model stdout yet)")
    stderr_text = Text("\n".join(state.model_stderr_lines[-18:]) or "(no model stderr yet)")

    top = Panel(status_table, title="Pipeline Status", border_style="cyan")
    left = Panel(orchestrator_text, title="Orchestrator Log", border_style="green")
    mid = Panel(stdout_text, title="Model Stdout", border_style="yellow")
    right = Panel(stderr_text, title="Model Stderr", border_style="red")

    lower = Table.grid(expand=True)
    lower.add_column(ratio=1)
    lower.add_column(ratio=1)
    lower.add_row(left, mid)
    lower.add_row(Panel("", border_style="black"), right)

    return Group(top, lower)


def run_ollama_streaming(
    *,
    ollama_bin: str,
    model: str,
    prompt_text: str,
    state: TUIState,
    live: Optional[Live],
    logger: JsonlLogger,
    chunk_name: str,
    pass_name: str,
    attempt: int,
) -> str:
    state.model_stdout_lines.clear()
    state.model_stderr_lines.clear()
    state.stdout_token_count = 0
    state.estimated_tps = None
    state.real_tps = None
    state.current_step = "launching model"

    logger.emit(
        level="INFO",
        event_type="model_launch",
        message="Launching Ollama model",
        chunk=chunk_name,
        pass_name=pass_name,
        step=state.current_step,
        model=model,
        attempt=attempt,
    )

    if live is not None:
        live.update(render_tui(state), refresh=True)

    proc = subprocess.Popen(
        [ollama_bin, "run", model],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    q: queue.Queue = queue.Queue()

    t_out = threading.Thread(target=stream_reader, args=(proc.stdout, q, "stdout"), daemon=True)
    t_err = threading.Thread(target=stream_reader, args=(proc.stderr, q, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    state.current_step = "sending prompt to model"
    if live is not None:
        live.update(render_tui(state), refresh=True)

    proc.stdin.write(prompt_text)
    proc.stdin.close()

    collected_stdout: List[str] = []
    collected_stderr: List[str] = []

    while True:
        try:
            stream_name, line = q.get(timeout=0.1)

            if stream_name == "stdout":
                collected_stdout.append(line)
                state.append_stdout(line)
                state.stdout_token_count += approx_token_count(line)
                state.current_step = "streaming model stdout"

                maybe_real_tps = extract_tps_from_text(line)
                if maybe_real_tps is not None:
                    state.real_tps = maybe_real_tps

            else:
                collected_stderr.append(line)
                state.append_stderr(line)
                state.current_step = "streaming model stderr"

                maybe_real_tps = extract_tps_from_text(line)
                if maybe_real_tps is not None:
                    state.real_tps = maybe_real_tps

            if state.pass_started_at is not None and state.real_tps is None:
                elapsed = max(time.time() - state.pass_started_at, 0.001)
                state.estimated_tps = state.stdout_token_count / elapsed

            if live is not None:
                live.update(render_tui(state), refresh=True)

        except queue.Empty:
            state.current_step = "waiting for model output"

            if state.pass_started_at is not None and state.real_tps is None:
                elapsed = max(time.time() - state.pass_started_at, 0.001)
                state.estimated_tps = state.stdout_token_count / elapsed

            if live is not None:
                live.update(render_tui(state), refresh=True)

            if proc.poll() is not None and q.empty():
                break

    return_code = proc.wait()
    stdout_text = "".join(collected_stdout).strip()
    stderr_text = "".join(collected_stderr).strip()

    # One last chance to detect a real tok/s line from full output.
    if state.real_tps is None:
        maybe_real_tps = extract_tps_from_text(stdout_text + "\n" + stderr_text)
        if maybe_real_tps is not None:
            state.real_tps = maybe_real_tps

    if return_code != 0:
        logger.emit(
            level="ERROR",
            event_type="model_failed",
            message="Ollama model exited with non-zero status",
            chunk=chunk_name,
            pass_name=pass_name,
            step=state.current_step,
            model=model,
            attempt=attempt,
            extra={"return_code": return_code},
        )
        raise RuntimeError(
            f"Ollama failed for model '{model}'.\nSTDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}"
        )

    if not stdout_text:
        logger.emit(
            level="ERROR",
            event_type="empty_output",
            message="Model returned empty stdout",
            chunk=chunk_name,
            pass_name=pass_name,
            step=state.current_step,
            model=model,
            attempt=attempt,
        )
        raise RuntimeError(f"Empty output from model '{model}'")

    logger.emit(
        level="INFO",
        event_type="model_completed",
        message="Model completed successfully",
        chunk=chunk_name,
        pass_name=pass_name,
        step="model complete",
        model=model,
        attempt=attempt,
        extra={
            "estimated_tps": state.estimated_tps,
            "reported_tps": state.real_tps,
            "stdout_chars": len(stdout_text),
            "stderr_chars": len(stderr_text),
        },
    )

    return stdout_text


def process_pass_once(
    *,
    ollama_bin: str,
    model: str,
    pass_name: str,
    input_text: str,
    raw_output_path: Path,
    json_output_path: Path,
    state: TUIState,
    live: Optional[Live],
    logger: JsonlLogger,
    chunk_name: str,
    attempt: int,
) -> Dict[str, Any]:
    state.current_pass = pass_name
    state.pass_status = "running"
    state.current_step = f"starting {pass_name}"
    state.pass_started_at = time.time()
    state.retries_used = max(0, attempt - 1)

    state.log(f"Starting pass: {pass_name} ({model}) attempt={attempt}")
    logger.emit(
        level="INFO",
        event_type="pass_start",
        message="Starting pass",
        chunk=chunk_name,
        pass_name=pass_name,
        step=state.current_step,
        model=model,
        attempt=attempt,
    )

    if live is not None:
        live.update(render_tui(state), refresh=True)

    raw = run_ollama_streaming(
        ollama_bin=ollama_bin,
        model=model,
        prompt_text=input_text,
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        pass_name=pass_name,
        attempt=attempt,
    )

    state.current_step = "writing raw output"
    if live is not None:
        live.update(render_tui(state), refresh=True)

    write_text(raw_output_path, raw + "\n")
    state.log(f"Wrote raw output: {raw_output_path}")
    logger.emit(
        level="INFO",
        event_type="raw_written",
        message="Wrote raw model output",
        chunk=chunk_name,
        pass_name=pass_name,
        step=state.current_step,
        model=model,
        attempt=attempt,
        extra={"path": str(raw_output_path)},
    )

    state.current_step = "parsing JSON"
    if live is not None:
        live.update(render_tui(state), refresh=True)

    parsed = extract_json(raw)

    state.current_step = "writing parsed JSON"
    if live is not None:
        live.update(render_tui(state), refresh=True)

    write_json(json_output_path, parsed)
    state.log(f"Wrote parsed JSON: {json_output_path}")
    logger.emit(
        level="INFO",
        event_type="json_written",
        message="Wrote parsed JSON",
        chunk=chunk_name,
        pass_name=pass_name,
        step=state.current_step,
        model=model,
        attempt=attempt,
        extra={"path": str(json_output_path)},
    )

    state.current_step = f"completed {pass_name}"
    state.pass_status = "done"
    state.log(f"Completed pass: {pass_name}")
    logger.emit(
        level="INFO",
        event_type="pass_success",
        message="Pass completed successfully",
        chunk=chunk_name,
        pass_name=pass_name,
        step=state.current_step,
        model=model,
        attempt=attempt,
        extra={"estimated_tps": state.estimated_tps, "reported_tps": state.real_tps},
    )

    if live is not None:
        live.update(render_tui(state), refresh=True)

    return parsed


def process_pass_with_retries(
    *,
    ollama_bin: str,
    model: str,
    pass_name: str,
    input_text: str,
    raw_output_path: Path,
    json_output_path: Path,
    state: TUIState,
    live: Optional[Live],
    logger: JsonlLogger,
    chunk_name: str,
    retries: int,
) -> Dict[str, Any]:
    last_exc: Optional[Exception] = None

    for attempt in range(1, retries + 2):
        try:
            return process_pass_once(
                ollama_bin=ollama_bin,
                model=model,
                pass_name=pass_name,
                input_text=input_text,
                raw_output_path=raw_output_path,
                json_output_path=json_output_path,
                state=state,
                live=live,
                logger=logger,
                chunk_name=chunk_name,
                attempt=attempt,
            )
        except Exception as exc:
            last_exc = exc
            state.pass_status = "retrying" if attempt <= retries else "failed"
            state.current_step = "handling error"
            state.log(f"ERROR in pass {pass_name} attempt={attempt}: {exc}")
            logger.emit(
                level="ERROR",
                event_type="pass_error",
                message=str(exc),
                chunk=chunk_name,
                pass_name=pass_name,
                step=state.current_step,
                model=model,
                attempt=attempt,
            )
            if live is not None:
                live.update(render_tui(state), refresh=True)

            if attempt <= retries:
                state.log(f"Retrying pass: {pass_name}")
                logger.emit(
                    level="WARNING",
                    event_type="pass_retry",
                    message="Retrying failed pass",
                    chunk=chunk_name,
                    pass_name=pass_name,
                    step="retry scheduled",
                    model=model,
                    attempt=attempt,
                )
                if live is not None:
                    live.update(render_tui(state), refresh=True)
                time.sleep(0.5)

    assert last_exc is not None
    raise last_exc


def process_chunk(
    chunk_path: Path,
    output_dir: Path,
    ollama_bin: str,
    state: TUIState,
    live: Optional[Live],
    logger: JsonlLogger,
    retries: int,
) -> None:
    chunk_name = chunk_path.stem
    state.current_chunk = chunk_name
    state.current_pass = "-"
    state.pass_status = "starting"
    state.current_step = "loading excerpt"
    state.pass_started_at = None
    state.retries_used = 0
    state.estimated_tps = None
    state.real_tps = None

    state.log(f"Processing chunk: {chunk_path}")
    logger.emit(
        level="INFO",
        event_type="chunk_start",
        message="Processing chunk",
        chunk=chunk_name,
        step=state.current_step,
        extra={"path": str(chunk_path)},
    )
    if live is not None:
        live.update(render_tui(state), refresh=True)

    excerpt_text = read_text(chunk_path)

    chunk_dir = output_dir / chunk_name
    chunk_dir.mkdir(parents=True, exist_ok=True)
    state.log(f"Created output directory: {chunk_dir}")
    logger.emit(
        level="INFO",
        event_type="chunk_dir_created",
        message="Created chunk output directory",
        chunk=chunk_name,
        step="mkdir",
        extra={"path": str(chunk_dir)},
    )
    if live is not None:
        live.update(render_tui(state), refresh=True)

    structure_json = process_pass_with_retries(
        ollama_bin=ollama_bin,
        model=STRUCTURE_MODEL,
        pass_name="structure",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "structure_raw.txt",
        json_output_path=chunk_dir / "structure.json",
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        retries=retries,
    )

    dialogue_json = process_pass_with_retries(
        ollama_bin=ollama_bin,
        model=DIALOGUE_MODEL,
        pass_name="dialogue",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "dialogue_raw.txt",
        json_output_path=chunk_dir / "dialogue.json",
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        retries=retries,
    )

    entities_json = process_pass_with_retries(
        ollama_bin=ollama_bin,
        model=ENTITIES_MODEL,
        pass_name="entities",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "entities_raw.txt",
        json_output_path=chunk_dir / "entities.json",
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        retries=retries,
    )

    state.current_step = "building dossier input"
    if live is not None:
        live.update(render_tui(state), refresh=True)

    dossier_input = build_dossier_input(excerpt_text, entities_json, dialogue_json)
    dossier_input_path = chunk_dir / "dossier_input.txt"
    write_text(dossier_input_path, dossier_input)

    state.log(f"Wrote dossier input: {dossier_input_path}")
    logger.emit(
        level="INFO",
        event_type="dossier_input_written",
        message="Wrote dossier input file",
        chunk=chunk_name,
        pass_name="dossiers",
        step=state.current_step,
        extra={"path": str(dossier_input_path)},
    )

    _ = structure_json  # reserved for future use

    process_pass_with_retries(
        ollama_bin=ollama_bin,
        model=DOSSIERS_MODEL,
        pass_name="dossiers",
        input_text=dossier_input,
        raw_output_path=chunk_dir / "dossiers_raw.txt",
        json_output_path=chunk_dir / "dossiers.json",
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        retries=retries,
    )

    state.pass_status = "chunk complete"
    state.current_step = "finished chunk"
    state.pass_started_at = None
    state.log(f"Finished chunk: {chunk_name}")
    state.chunks_completed += 1

    logger.emit(
        level="INFO",
        event_type="chunk_success",
        message="Chunk completed successfully",
        chunk=chunk_name,
        step=state.current_step,
    )

    if live is not None:
        live.update(render_tui(state), refresh=True)


def write_chunk_error(chunk_dir: Path, chunk_name: str, exc: Exception) -> None:
    error_path = chunk_dir / "error.txt"
    write_text(error_path, f"[{utc_now_iso()}] {chunk_name}: {exc}\n")


def run_plain(
    args: argparse.Namespace,
    logger: JsonlLogger,
) -> int:
    state = TUIState()
    try:
        chunk_files = collect_inputs(args)
        state.chunks_total = len(chunk_files)
        args.output_dir.mkdir(parents=True, exist_ok=True)

        logger.emit(
            level="INFO",
            event_type="run_start",
            message="Starting pipeline run",
            extra={
                "chunks_total": state.chunks_total,
                "output_dir": str(args.output_dir),
                "retries": args.retries,
                "on_failure": args.on_failure,
            },
        )

        for chunk_path in chunk_files:
            try:
                process_chunk(
                    chunk_path=chunk_path,
                    output_dir=args.output_dir,
                    ollama_bin=args.ollama_bin,
                    state=state,
                    live=None,
                    logger=logger,
                    retries=args.retries,
                )
            except Exception as exc:
                state.chunks_failed += 1
                chunk_dir = args.output_dir / chunk_path.stem
                chunk_dir.mkdir(parents=True, exist_ok=True)
                write_chunk_error(chunk_dir, chunk_path.stem, exc)
                logger.emit(
                    level="ERROR",
                    event_type="chunk_failure",
                    message=str(exc),
                    chunk=chunk_path.stem,
                    step="chunk failed",
                )
                if args.on_failure == "stop":
                    raise

        logger.emit(
            level="INFO",
            event_type="run_complete",
            message="Pipeline run completed",
            extra={
                "chunks_total": state.chunks_total,
                "chunks_completed": state.chunks_completed,
                "chunks_failed": state.chunks_failed,
            },
        )

        print("[DONE] Pipeline run completed.")
        return 0 if state.chunks_failed == 0 else 1

    except Exception as exc:
        logger.emit(
            level="ERROR",
            event_type="run_abort",
            message=str(exc),
        )
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


def main() -> int:
    args = parse_args()

    run_id = str(uuid.uuid4())
    log_path = args.log_file or (args.output_dir / "orchestrator.log.jsonl")
    logger = JsonlLogger(log_path, run_id)

    if args.no_tui:
        return run_plain(args, logger)

    state = TUIState()

    try:
        chunk_files = collect_inputs(args)
        state.chunks_total = len(chunk_files)
        args.output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.emit(
            level="ERROR",
            event_type="startup_error",
            message=str(exc),
        )
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    failures: List[str] = []

    logger.emit(
        level="INFO",
        event_type="run_start",
        message="Starting pipeline run",
        extra={
            "chunks_total": state.chunks_total,
            "output_dir": str(args.output_dir),
            "retries": args.retries,
            "on_failure": args.on_failure,
            "log_file": str(log_path),
        },
    )

    with Live(render_tui(state), refresh_per_second=8, screen=True) as live:
        try:
            for chunk_path in chunk_files:
                try:
                    process_chunk(
                        chunk_path=chunk_path,
                        output_dir=args.output_dir,
                        ollama_bin=args.ollama_bin,
                        state=state,
                        live=live,
                        logger=logger,
                        retries=args.retries,
                    )
                except Exception as exc:
                    failures.append(f"{chunk_path.name}: {exc}")
                    state.chunks_failed += 1
                    chunk_dir = args.output_dir / chunk_path.stem
                    chunk_dir.mkdir(parents=True, exist_ok=True)
                    write_chunk_error(chunk_dir, chunk_path.stem, exc)

                    state.pass_status = "failed"
                    state.current_step = "error"
                    state.log(f"ERROR: {chunk_path.name}: {exc}")

                    logger.emit(
                        level="ERROR",
                        event_type="chunk_failure",
                        message=str(exc),
                        chunk=chunk_path.stem,
                        step="chunk failed",
                    )

                    live.update(render_tui(state), refresh=True)

                    if args.on_failure == "stop":
                        break

                time.sleep(0.2)
        finally:
            live.update(render_tui(state), refresh=True)

    logger.emit(
        level="INFO",
        event_type="run_complete",
        message="Pipeline run completed",
        extra={
            "chunks_total": state.chunks_total,
            "chunks_completed": state.chunks_completed,
            "chunks_failed": state.chunks_failed,
            "failures": failures,
        },
    )

    if failures:
        print("[SUMMARY] Some chunks failed:", file=sys.stderr)
        for err in failures:
            print(f"- {err}", file=sys.stderr)
        return 1

    print("[DONE] All chunks processed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())