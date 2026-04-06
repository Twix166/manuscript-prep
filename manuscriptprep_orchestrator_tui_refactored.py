#!/usr/bin/env python3
"""
manuscriptprep_orchestrator_tui.py

A live TUI orchestrator for a 4-pass Ollama manuscript pipeline.

Status:
- This is the canonical supported orchestrator entry point for the current repository.

Passes:
1. structure
2. dialogue
3. entities
4. dossiers

This refactor keeps the original interactive behavior while adding a shared
config-aware runtime model. The orchestrator can now load defaults from a YAML
config file and still allow CLI flags to override them.

Supported config sections:
- paths
- models
- ollama
- timeouts
- logging
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

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required for config support. Install with: pip install pyyaml") from exc


TPS_PATTERNS = [
    re.compile(r"(?i)\b(eval(?:uation)?(?:\s+rate)?|tokens?/s|tok/s)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)"),
    re.compile(r"(?i)\b([0-9]+(?:\.[0-9]+)?)\s*(?:tokens?/s|tok/s)\b"),
]


@dataclass
class RuntimeConfig:
    structure_model: str = "manuscriptprep-structure"
    dialogue_model: str = "manuscriptprep-dialogue"
    entities_model: str = "manuscriptprep-entities"
    dossiers_model: str = "manuscriptprep-dossiers"
    ollama_bin: str = "ollama"
    retries: int = 1
    on_failure: str = "skip"
    idle_timeout: int = 180
    idle_timeout_backoff: float = 1.5
    max_idle_timeout: int = 600
    hard_timeout: int = 900
    log_level: str = "INFO"
    log_console: bool = True
    logs_root: Optional[Path] = None


@dataclass
class TUIState:
    current_chunk: str = "-"
    current_pass: str = "-"
    pass_status: str = "idle"
    current_step: str = "-"

    chunk_started_at: Optional[float] = None
    pass_started_at: Optional[float] = None

    chunks_total: int = 0
    chunks_completed: int = 0
    chunks_failed: int = 0

    retries_used: int = 0

    estimated_tps: Optional[float] = None
    real_tps: Optional[float] = None
    stdout_token_count: int = 0

    last_stdout_at: Optional[float] = None
    last_stderr_at: Optional[float] = None

    current_pass_duration: Optional[float] = None
    current_chunk_duration: Optional[float] = None

    current_idle_timeout: Optional[int] = None
    idle_timeout_failures_for_pass: int = 0

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
        self.last_stdout_at = time.time()

    def append_stderr(self, line: str) -> None:
        self.model_stderr_lines.append(line.rstrip("\n"))
        self.model_stderr_lines = self.model_stderr_lines[-250:]
        self.last_stderr_at = time.time()


class JsonlLogger:
    """Write structured JSONL events suitable for observability tooling."""

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


class PassTimeoutError(RuntimeError):
    pass


class IdleTimeoutError(PassTimeoutError):
    pass


class HardTimeoutError(PassTimeoutError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def natural_key(path: Path) -> List[Any]:
    parts = re.split(r"(\d+)", path.name)
    key: List[Any] = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        else:
            key.append(p.lower())
    return key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a 4-pass manuscript pipeline with a live terminal UI, config support, and timing."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="Single chunk text file")
    group.add_argument("--input-dir", type=Path, help="Directory containing chunk text files")

    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for outputs")
    parser.add_argument("--config", type=Path, default=None, help="Optional YAML config file")
    parser.add_argument("--book-slug", default=None, help="Optional book slug used when deriving paths from config")
    parser.add_argument("--glob", default="*.txt", help="Glob for input-dir mode")
    parser.add_argument("--no-tui", action="store_true", help="Disable TUI and use plain logging")

    parser.add_argument("--ollama-bin", default=None, help="Path to ollama binary")
    parser.add_argument("--structure-model", default=None, help="Override structure model")
    parser.add_argument("--dialogue-model", default=None, help="Override dialogue model")
    parser.add_argument("--entities-model", default=None, help="Override entities model")
    parser.add_argument("--dossiers-model", default=None, help="Override dossiers model")

    parser.add_argument("--retries", type=int, default=None, help="Retries per pass after first failure")
    parser.add_argument(
        "--on-failure",
        choices=["skip", "stop"],
        default=None,
        help="Skip failed chunk or stop entire run",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Structured JSONL log file path. Defaults to config logs_root or <output-dir>/orchestrator.log.jsonl",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=None,
        help="Base seconds with no stdout/stderr before pass is treated as stalled",
    )
    parser.add_argument(
        "--idle-timeout-backoff",
        type=float,
        default=None,
        help="Multiplier applied after each idle-timeout failure for the same pass",
    )
    parser.add_argument(
        "--max-idle-timeout",
        type=int,
        default=None,
        help="Maximum idle timeout allowed after backoff",
    )
    parser.add_argument(
        "--hard-timeout",
        type=int,
        default=None,
        help="Maximum total seconds allowed for a single pass",
    )
    return parser.parse_args()


def load_yaml_config(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise RuntimeError(f"Config file does not exist: {resolved}")
    with resolved.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError("Top-level config must be a mapping/object")
    return data


def build_runtime_config(args: argparse.Namespace, config_data: Dict[str, Any]) -> RuntimeConfig:
    models = config_data.get("models", {})
    timeouts = config_data.get("timeouts", {})
    logging_cfg = config_data.get("logging", {})
    ollama_cfg = config_data.get("ollama", {})
    paths_cfg = config_data.get("paths", {})

    logs_root = paths_cfg.get("logs_root")
    return RuntimeConfig(
        structure_model=args.structure_model or models.get("structure", "manuscriptprep-structure"),
        dialogue_model=args.dialogue_model or models.get("dialogue", "manuscriptprep-dialogue"),
        entities_model=args.entities_model or models.get("entities", "manuscriptprep-entities"),
        dossiers_model=args.dossiers_model or models.get("dossiers", "manuscriptprep-dossiers"),
        ollama_bin=args.ollama_bin or ollama_cfg.get("command", "ollama"),
        retries=args.retries if args.retries is not None else int(timeouts.get("retries", 1)),
        on_failure=args.on_failure or "skip",
        idle_timeout=args.idle_timeout if args.idle_timeout is not None else int(timeouts.get("idle_seconds", 180)),
        idle_timeout_backoff=(
            args.idle_timeout_backoff
            if args.idle_timeout_backoff is not None
            else float(timeouts.get("idle_timeout_backoff", 1.5))
        ),
        max_idle_timeout=(
            args.max_idle_timeout if args.max_idle_timeout is not None else int(timeouts.get("max_idle_timeout_seconds", 600))
        ),
        hard_timeout=args.hard_timeout if args.hard_timeout is not None else int(timeouts.get("hard_seconds", 900)),
        log_level=str(logging_cfg.get("level", "INFO")),
        log_console=bool(logging_cfg.get("console", True)),
        logs_root=Path(logs_root).expanduser() if logs_root else None,
    )


def resolve_output_dir(args: argparse.Namespace, config_data: Dict[str, Any]) -> Path:
    if args.output_dir is not None:
        return args.output_dir.expanduser()

    paths_cfg = config_data.get("paths", {})
    output_root = paths_cfg.get("output_root")
    if not output_root:
        raise RuntimeError("No output directory supplied. Use --output-dir or set paths.output_root in config.")

    if args.book_slug:
        slug = args.book_slug
    elif args.input_dir:
        slug = args.input_dir.name
    else:
        slug = args.input.stem

    return Path(output_root).expanduser() / slug


def resolve_log_path(args: argparse.Namespace, output_dir: Path, runtime: RuntimeConfig) -> Path:
    if args.log_file is not None:
        return args.log_file.expanduser()
    if runtime.logs_root is not None:
        return runtime.logs_root / "orchestrator.log.jsonl"
    return output_dir / "orchestrator.log.jsonl"


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

    files = sorted(args.input_dir.glob(args.glob), key=natural_key)
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
    return len(re.findall(r"\S+", text))


def extract_tps_from_text(text: str) -> Optional[float]:
    for pattern in TPS_PATTERNS:
        m = pattern.search(text)
        if m:
            for g in reversed(m.groups()):
                try:
                    return float(g)
                except (TypeError, ValueError):
                    continue
    return None


def fmt_age(ts: Optional[float]) -> str:
    if ts is None:
        return "-"
    return f"{max(0.0, time.time() - ts):.1f}s"


def fmt_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    return f"{seconds:.1f}s"


def kill_process_tree(proc: subprocess.Popen) -> None:
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def compute_effective_idle_timeout(
    base_idle_timeout: int,
    idle_timeout_backoff: float,
    max_idle_timeout: int,
    idle_timeout_failures_for_pass: int,
) -> int:
    effective = int(round(base_idle_timeout * (idle_timeout_backoff ** idle_timeout_failures_for_pass)))
    return min(max_idle_timeout, max(1, effective))


def render_tui(state: TUIState):
    now = time.time()

    pass_elapsed = state.current_pass_duration
    if state.pass_started_at is not None and state.pass_status == "running":
        pass_elapsed = now - state.pass_started_at

    chunk_elapsed = state.current_chunk_duration
    if state.chunk_started_at is not None and state.current_chunk not in ("-", ""):
        if state.pass_status not in ("chunk complete", "failed"):
            chunk_elapsed = now - state.chunk_started_at

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
    status_table.add_row("Pass elapsed", fmt_duration(pass_elapsed))
    status_table.add_row("Chunk elapsed", fmt_duration(chunk_elapsed))
    status_table.add_row("Progress", progress)
    status_table.add_row("Retries", str(state.retries_used))
    status_table.add_row("Idle timeout", str(state.current_idle_timeout) if state.current_idle_timeout else "-")
    status_table.add_row("Idle backoffs", str(state.idle_timeout_failures_for_pass))
    status_table.add_row("Token speed", tps_display)
    status_table.add_row("Last stdout", fmt_age(state.last_stdout_at))
    status_table.add_row("Last stderr", fmt_age(state.last_stderr_at))

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
    runtime: RuntimeConfig,
    model: str,
    prompt_text: str,
    state: TUIState,
    live: Optional[Live],
    logger: JsonlLogger,
    chunk_name: str,
    pass_name: str,
    attempt: int,
    idle_timeout: int,
    hard_timeout: int,
) -> str:
    state.model_stdout_lines.clear()
    state.model_stderr_lines.clear()
    state.stdout_token_count = 0
    state.estimated_tps = None
    state.real_tps = None
    state.last_stdout_at = None
    state.last_stderr_at = None
    state.current_step = "launching model"
    state.current_idle_timeout = idle_timeout

    logger.emit(
        level="INFO",
        event_type="model_launch",
        message="Launching Ollama model",
        chunk=chunk_name,
        pass_name=pass_name,
        step=state.current_step,
        model=model,
        attempt=attempt,
        extra={"idle_timeout_s": idle_timeout, "hard_timeout_s": hard_timeout, "ollama_bin": runtime.ollama_bin},
    )

    if live is not None:
        live.update(render_tui(state), refresh=True)

    proc = subprocess.Popen(
        [runtime.ollama_bin, "run", model],
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

    started_at = time.time()
    last_activity_at = started_at

    collected_stdout: List[str] = []
    collected_stderr: List[str] = []

    while True:
        now = time.time()

        if hard_timeout > 0 and (now - started_at) > hard_timeout:
            state.current_step = "hard timeout reached"
            logger.emit(
                level="ERROR",
                event_type="pass_hard_timeout",
                message="Hard timeout reached; killing process",
                chunk=chunk_name,
                pass_name=pass_name,
                step=state.current_step,
                model=model,
                attempt=attempt,
                extra={"elapsed_s": now - started_at, "idle_timeout_s": idle_timeout},
            )
            kill_process_tree(proc)
            raise HardTimeoutError(
                f"Hard timeout exceeded for {pass_name} on {chunk_name} after {hard_timeout}s"
            )

        if idle_timeout > 0 and (now - last_activity_at) > idle_timeout:
            state.current_step = "idle timeout reached"
            logger.emit(
                level="ERROR",
                event_type="pass_idle_timeout",
                message="Idle timeout reached; killing process",
                chunk=chunk_name,
                pass_name=pass_name,
                step=state.current_step,
                model=model,
                attempt=attempt,
                extra={
                    "idle_s": now - last_activity_at,
                    "elapsed_s": now - started_at,
                    "idle_timeout_s": idle_timeout,
                },
            )
            kill_process_tree(proc)
            raise IdleTimeoutError(
                f"Idle timeout exceeded for {pass_name} on {chunk_name} after {idle_timeout}s with no output"
            )

        try:
            stream_name, line = q.get(timeout=0.2)
            last_activity_at = time.time()

            if stream_name == "stdout":
                collected_stdout.append(line)
                state.append_stdout(line)
                state.current_step = "streaming model stdout"
                state.stdout_token_count += approx_token_count(line)

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

    if state.real_tps is None:
        maybe_real_tps = extract_tps_from_text(stdout_text + "\n" + stderr_text)
        if maybe_real_tps is not None:
            state.real_tps = maybe_real_tps

    model_elapsed = time.time() - started_at

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
            extra={"return_code": return_code, "duration_seconds": model_elapsed},
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
            extra={"duration_seconds": model_elapsed},
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
            "duration_seconds": model_elapsed,
            "idle_timeout_s": idle_timeout,
        },
    )

    return stdout_text


def process_pass_once(
    *,
    runtime: RuntimeConfig,
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
    idle_timeout: int,
    hard_timeout: int,
) -> Tuple[Dict[str, Any], float]:
    state.current_pass = pass_name
    state.pass_status = "running"
    state.current_step = f"starting {pass_name}"
    state.pass_started_at = time.time()
    state.current_pass_duration = None
    state.retries_used = max(0, attempt - 1)
    state.current_idle_timeout = idle_timeout

    state.log(f"Starting pass: {pass_name} ({model}) attempt={attempt} idle_timeout={idle_timeout}s")
    logger.emit(
        level="INFO",
        event_type="pass_start",
        message="Starting pass",
        chunk=chunk_name,
        pass_name=pass_name,
        step=state.current_step,
        model=model,
        attempt=attempt,
        extra={"idle_timeout_s": idle_timeout},
    )

    if live is not None:
        live.update(render_tui(state), refresh=True)

    raw = run_ollama_streaming(
        runtime=runtime,
        model=model,
        prompt_text=input_text,
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        pass_name=pass_name,
        attempt=attempt,
        idle_timeout=idle_timeout,
        hard_timeout=hard_timeout,
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

    duration = time.time() - state.pass_started_at
    state.current_pass_duration = duration

    state.current_step = f"completed {pass_name}"
    state.pass_status = "done"
    state.log(f"Completed pass: {pass_name} ({duration:.1f}s)")
    logger.emit(
        level="INFO",
        event_type="pass_success",
        message="Pass completed successfully",
        chunk=chunk_name,
        pass_name=pass_name,
        step=state.current_step,
        model=model,
        attempt=attempt,
        extra={
            "estimated_tps": state.estimated_tps,
            "reported_tps": state.real_tps,
            "duration_seconds": duration,
            "idle_timeout_s": idle_timeout,
        },
    )

    if live is not None:
        live.update(render_tui(state), refresh=True)

    return parsed, duration


def process_pass_with_retries(
    *,
    runtime: RuntimeConfig,
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
    base_idle_timeout: int,
    idle_timeout_backoff: float,
    max_idle_timeout: int,
    hard_timeout: int,
) -> Tuple[Dict[str, Any], float]:
    last_exc: Optional[Exception] = None
    idle_timeout_failures_for_pass = 0
    state.idle_timeout_failures_for_pass = 0

    for attempt in range(1, retries + 2):
        effective_idle_timeout = compute_effective_idle_timeout(
            base_idle_timeout=base_idle_timeout,
            idle_timeout_backoff=idle_timeout_backoff,
            max_idle_timeout=max_idle_timeout,
            idle_timeout_failures_for_pass=idle_timeout_failures_for_pass,
        )
        state.current_idle_timeout = effective_idle_timeout
        state.idle_timeout_failures_for_pass = idle_timeout_failures_for_pass

        try:
            return process_pass_once(
                runtime=runtime,
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
                idle_timeout=effective_idle_timeout,
                hard_timeout=hard_timeout,
            )
        except Exception as exc:
            last_exc = exc

            if isinstance(exc, IdleTimeoutError):
                idle_timeout_failures_for_pass += 1
                state.idle_timeout_failures_for_pass = idle_timeout_failures_for_pass

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
                extra={
                    "idle_timeout_s": effective_idle_timeout,
                    "idle_timeout_failures_for_pass": idle_timeout_failures_for_pass,
                    "error_class": exc.__class__.__name__,
                },
            )

            if live is not None:
                live.update(render_tui(state), refresh=True)

            if attempt <= retries:
                next_idle_timeout = compute_effective_idle_timeout(
                    base_idle_timeout=base_idle_timeout,
                    idle_timeout_backoff=idle_timeout_backoff,
                    max_idle_timeout=max_idle_timeout,
                    idle_timeout_failures_for_pass=idle_timeout_failures_for_pass,
                )

                if isinstance(exc, IdleTimeoutError):
                    state.log(
                        f"Retrying pass: {pass_name} with increased idle timeout "
                        f"{effective_idle_timeout}s -> {next_idle_timeout}s"
                    )
                    logger.emit(
                        level="WARNING",
                        event_type="pass_retry_idle_timeout_backoff",
                        message="Retrying failed pass with increased idle timeout",
                        chunk=chunk_name,
                        pass_name=pass_name,
                        step="retry scheduled",
                        model=model,
                        attempt=attempt,
                        extra={
                            "previous_idle_timeout_s": effective_idle_timeout,
                            "next_idle_timeout_s": next_idle_timeout,
                            "idle_timeout_failures_for_pass": idle_timeout_failures_for_pass,
                        },
                    )
                else:
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
                        extra={"idle_timeout_s": effective_idle_timeout},
                    )

                if live is not None:
                    live.update(render_tui(state), refresh=True)
                time.sleep(0.5)

    assert last_exc is not None
    raise last_exc


def process_chunk(
    chunk_path: Path,
    output_dir: Path,
    runtime: RuntimeConfig,
    state: TUIState,
    live: Optional[Live],
    logger: JsonlLogger,
) -> None:
    chunk_name = chunk_path.stem
    state.current_chunk = chunk_name
    state.current_pass = "-"
    state.pass_status = "starting"
    state.current_step = "loading excerpt"
    state.chunk_started_at = time.time()
    state.current_chunk_duration = None
    state.pass_started_at = None
    state.current_pass_duration = None
    state.retries_used = 0
    state.estimated_tps = None
    state.real_tps = None
    state.last_stdout_at = None
    state.last_stderr_at = None
    state.current_idle_timeout = runtime.idle_timeout
    state.idle_timeout_failures_for_pass = 0

    pass_timings: Dict[str, float] = {}

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

    structure_json, structure_duration = process_pass_with_retries(
        runtime=runtime,
        model=runtime.structure_model,
        pass_name="structure",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "structure_raw.txt",
        json_output_path=chunk_dir / "structure.json",
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        retries=runtime.retries,
        base_idle_timeout=runtime.idle_timeout,
        idle_timeout_backoff=runtime.idle_timeout_backoff,
        max_idle_timeout=runtime.max_idle_timeout,
        hard_timeout=runtime.hard_timeout,
    )
    pass_timings["structure"] = structure_duration

    dialogue_json, dialogue_duration = process_pass_with_retries(
        runtime=runtime,
        model=runtime.dialogue_model,
        pass_name="dialogue",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "dialogue_raw.txt",
        json_output_path=chunk_dir / "dialogue.json",
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        retries=runtime.retries,
        base_idle_timeout=runtime.idle_timeout,
        idle_timeout_backoff=runtime.idle_timeout_backoff,
        max_idle_timeout=runtime.max_idle_timeout,
        hard_timeout=runtime.hard_timeout,
    )
    pass_timings["dialogue"] = dialogue_duration

    entities_json, entities_duration = process_pass_with_retries(
        runtime=runtime,
        model=runtime.entities_model,
        pass_name="entities",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "entities_raw.txt",
        json_output_path=chunk_dir / "entities.json",
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        retries=runtime.retries,
        base_idle_timeout=runtime.idle_timeout,
        idle_timeout_backoff=runtime.idle_timeout_backoff,
        max_idle_timeout=runtime.max_idle_timeout,
        hard_timeout=runtime.hard_timeout,
    )
    pass_timings["entities"] = entities_duration

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

    _ = structure_json

    dossiers_json, dossiers_duration = process_pass_with_retries(
        runtime=runtime,
        model=runtime.dossiers_model,
        pass_name="dossiers",
        input_text=dossier_input,
        raw_output_path=chunk_dir / "dossiers_raw.txt",
        json_output_path=chunk_dir / "dossiers.json",
        state=state,
        live=live,
        logger=logger,
        chunk_name=chunk_name,
        retries=runtime.retries,
        base_idle_timeout=runtime.idle_timeout,
        idle_timeout_backoff=runtime.idle_timeout_backoff,
        max_idle_timeout=runtime.max_idle_timeout,
        hard_timeout=runtime.hard_timeout,
    )
    pass_timings["dossiers"] = dossiers_duration

    _ = dossiers_json

    chunk_duration = time.time() - state.chunk_started_at
    state.current_chunk_duration = chunk_duration

    timing_json = {
        "chunk": chunk_name,
        "total_duration_seconds": chunk_duration,
        "passes": pass_timings,
    }
    write_json(chunk_dir / "timing.json", timing_json)

    state.pass_status = "chunk complete"
    state.current_step = "finished chunk"
    state.pass_started_at = None
    state.current_pass_duration = None
    state.log(f"Finished chunk: {chunk_name} ({chunk_duration:.1f}s)")
    state.chunks_completed += 1

    logger.emit(
        level="INFO",
        event_type="chunk_success",
        message="Chunk completed successfully",
        chunk=chunk_name,
        step=state.current_step,
        extra={
            "duration_seconds": chunk_duration,
            "pass_durations": pass_timings,
            "timing_json_path": str(chunk_dir / "timing.json"),
        },
    )

    if live is not None:
        live.update(render_tui(state), refresh=True)


def write_chunk_error(chunk_dir: Path, chunk_name: str, exc: Exception) -> None:
    error_path = chunk_dir / "error.txt"
    write_text(error_path, f"[{utc_now_iso()}] {chunk_name}: {exc}\n")


def run_plain(args: argparse.Namespace, runtime: RuntimeConfig, output_dir: Path, logger: JsonlLogger) -> int:
    state = TUIState()
    try:
        chunk_files = collect_inputs(args)
        state.chunks_total = len(chunk_files)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.emit(
            level="INFO",
            event_type="run_start",
            message="Starting pipeline run",
            extra={
                "chunks_total": state.chunks_total,
                "output_dir": str(output_dir),
                "retries": runtime.retries,
                "on_failure": runtime.on_failure,
                "idle_timeout_s": runtime.idle_timeout,
                "idle_timeout_backoff": runtime.idle_timeout_backoff,
                "max_idle_timeout_s": runtime.max_idle_timeout,
                "hard_timeout_s": runtime.hard_timeout,
                "models": {
                    "structure": runtime.structure_model,
                    "dialogue": runtime.dialogue_model,
                    "entities": runtime.entities_model,
                    "dossiers": runtime.dossiers_model,
                },
            },
        )

        for chunk_path in chunk_files:
            try:
                process_chunk(
                    chunk_path=chunk_path,
                    output_dir=output_dir,
                    runtime=runtime,
                    state=state,
                    live=None,
                    logger=logger,
                )
            except Exception as exc:
                state.chunks_failed += 1
                chunk_dir = output_dir / chunk_path.stem
                chunk_dir.mkdir(parents=True, exist_ok=True)
                write_chunk_error(chunk_dir, chunk_path.stem, exc)
                logger.emit(
                    level="ERROR",
                    event_type="chunk_failure",
                    message=str(exc),
                    chunk=chunk_path.stem,
                    step="chunk failed",
                )
                if runtime.on_failure == "stop":
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

    try:
        config_data = load_yaml_config(args.config)
        runtime = build_runtime_config(args, config_data)
        output_dir = resolve_output_dir(args, config_data)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    run_id = str(uuid.uuid4())
    log_path = resolve_log_path(args, output_dir, runtime)
    logger = JsonlLogger(log_path, run_id)

    if args.no_tui:
        return run_plain(args, runtime, output_dir, logger)

    state = TUIState()

    try:
        chunk_files = collect_inputs(args)
        state.chunks_total = len(chunk_files)
        output_dir.mkdir(parents=True, exist_ok=True)
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
            "output_dir": str(output_dir),
            "config_path": str(args.config) if args.config else None,
            "retries": runtime.retries,
            "on_failure": runtime.on_failure,
            "log_file": str(log_path),
            "idle_timeout_s": runtime.idle_timeout,
            "idle_timeout_backoff": runtime.idle_timeout_backoff,
            "max_idle_timeout_s": runtime.max_idle_timeout,
            "hard_timeout_s": runtime.hard_timeout,
            "models": {
                "structure": runtime.structure_model,
                "dialogue": runtime.dialogue_model,
                "entities": runtime.entities_model,
                "dossiers": runtime.dossiers_model,
            },
        },
    )

    with Live(render_tui(state), refresh_per_second=8, screen=True) as live:
        try:
            for chunk_path in chunk_files:
                try:
                    process_chunk(
                        chunk_path=chunk_path,
                        output_dir=output_dir,
                        runtime=runtime,
                        state=state,
                        live=live,
                        logger=logger,
                    )
                except Exception as exc:
                    failures.append(f"{chunk_path.name}: {exc}")
                    state.chunks_failed += 1
                    chunk_dir = output_dir / chunk_path.stem
                    chunk_dir.mkdir(parents=True, exist_ok=True)
                    write_chunk_error(chunk_dir, chunk_path.stem, exc)

                    if state.chunk_started_at is not None:
                        state.current_chunk_duration = time.time() - state.chunk_started_at

                    state.pass_status = "failed"
                    state.current_step = "error"
                    state.log(f"ERROR: {chunk_path.name}: {exc}")

                    logger.emit(
                        level="ERROR",
                        event_type="chunk_failure",
                        message=str(exc),
                        chunk=chunk_path.stem,
                        step="chunk failed",
                        extra={"chunk_duration_seconds": state.current_chunk_duration},
                    )

                    live.update(render_tui(state), refresh=True)

                    if runtime.on_failure == "stop":
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
