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

Usage:
    python manuscriptprep_orchestrator_tui.py --input chunk_0.txt --output-dir out
    python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out

Optional:
    python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out --ollama-bin /usr/local/bin/ollama
    python manuscriptprep_orchestrator_tui.py --input-dir chunks --output-dir out --no-tui
"""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


STRUCTURE_MODEL = "manuscriptprep-structure"
DIALOGUE_MODEL = "manuscriptprep-dialogue"
ENTITIES_MODEL = "manuscriptprep-entities"
DOSSIERS_MODEL = "manuscriptprep-dossiers"


@dataclass
class TUIState:
    current_chunk: str = "-"
    current_pass: str = "-"
    pass_status: str = "idle"
    current_step: str = "-"
    pass_started_at: Optional[float] = None
    chunks_total: int = 0
    chunks_completed: int = 0
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a 4-pass manuscript pipeline with a live terminal UI."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="Single chunk text file")
    group.add_argument("--input-dir", type=Path, help="Directory containing chunk text files")

    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for outputs")
    parser.add_argument("--ollama-bin", default="ollama", help="Path to ollama binary")
    parser.add_argument("--glob", default="*.txt", help="Glob for input-dir mode")
    parser.add_argument("--no-tui", action="store_true", help="Disable TUI and use plain logging")
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
            raise RuntimeError(f"Model output is not valid JSON:\n{text}")
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Model output is not valid JSON:\n{text}") from exc


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


def render_tui(state: TUIState):
    elapsed = "-"
    if state.pass_started_at is not None:
        elapsed = f"{time.time() - state.pass_started_at:.1f}s"

    progress = "-"
    if state.chunks_total > 0:
        progress = f"{state.chunks_completed}/{state.chunks_total}"

    status_table = Table.grid(expand=True)
    status_table.add_column(ratio=1)
    status_table.add_column(ratio=3)
    status_table.add_row("Chunk", state.current_chunk)
    status_table.add_row("Pass", state.current_pass)
    status_table.add_row("Status", state.pass_status)
    status_table.add_row("Step", state.current_step)
    status_table.add_row("Elapsed", elapsed)
    status_table.add_row("Progress", progress)

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
) -> str:
    state.model_stdout_lines.clear()
    state.model_stderr_lines.clear()
    state.current_step = "launching model"

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
                state.current_step = "streaming model stdout"
            else:
                collected_stderr.append(line)
                state.append_stderr(line)
                state.current_step = "streaming model stderr"

            if live is not None:
                live.update(render_tui(state), refresh=True)

        except queue.Empty:
            state.current_step = "waiting for model output"
            if live is not None:
                live.update(render_tui(state), refresh=True)
            if proc.poll() is not None and q.empty():
                break

    return_code = proc.wait()
    stdout_text = "".join(collected_stdout).strip()
    stderr_text = "".join(collected_stderr).strip()

    if return_code != 0:
        raise RuntimeError(
            f"Ollama failed for model '{model}'.\nSTDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}"
        )

    if not stdout_text:
        raise RuntimeError(f"Empty output from model '{model}'")

    return stdout_text


def process_pass(
    *,
    ollama_bin: str,
    model: str,
    pass_name: str,
    input_text: str,
    raw_output_path: Path,
    json_output_path: Path,
    state: TUIState,
    live: Optional[Live],
) -> Dict[str, Any]:
    state.current_pass = pass_name
    state.pass_status = "running"
    state.current_step = f"starting {pass_name}"
    state.pass_started_at = time.time()
    state.log(f"Starting pass: {pass_name} ({model})")
    if live is not None:
        live.update(render_tui(state), refresh=True)

    raw = run_ollama_streaming(
        ollama_bin=ollama_bin,
        model=model,
        prompt_text=input_text,
        state=state,
        live=live,
    )

    state.current_step = "writing raw output"
    if live is not None:
        live.update(render_tui(state), refresh=True)
    write_text(raw_output_path, raw + "\n")
    state.log(f"Wrote raw output: {raw_output_path}")

    state.current_step = "parsing JSON"
    if live is not None:
        live.update(render_tui(state), refresh=True)
    parsed = extract_json(raw)

    state.current_step = "writing parsed JSON"
    if live is not None:
        live.update(render_tui(state), refresh=True)
    write_json(json_output_path, parsed)
    state.log(f"Wrote parsed JSON: {json_output_path}")

    state.current_step = f"completed {pass_name}"
    state.pass_status = "done"
    state.log(f"Completed pass: {pass_name}")
    if live is not None:
        live.update(render_tui(state), refresh=True)

    return parsed


def process_chunk(
    chunk_path: Path,
    output_dir: Path,
    ollama_bin: str,
    state: TUIState,
    live: Optional[Live],
) -> None:
    chunk_name = chunk_path.stem
    state.current_chunk = chunk_name
    state.current_pass = "-"
    state.pass_status = "starting"
    state.current_step = "loading excerpt"
    state.pass_started_at = None
    state.log(f"Processing chunk: {chunk_path}")
    if live is not None:
        live.update(render_tui(state), refresh=True)

    excerpt_text = read_text(chunk_path)

    chunk_dir = output_dir / chunk_name
    chunk_dir.mkdir(parents=True, exist_ok=True)
    state.log(f"Created output directory: {chunk_dir}")
    if live is not None:
        live.update(render_tui(state), refresh=True)

    _structure_json = process_pass(
        ollama_bin=ollama_bin,
        model=STRUCTURE_MODEL,
        pass_name="structure",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "structure_raw.txt",
        json_output_path=chunk_dir / "structure.json",
        state=state,
        live=live,
    )

    dialogue_json = process_pass(
        ollama_bin=ollama_bin,
        model=DIALOGUE_MODEL,
        pass_name="dialogue",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "dialogue_raw.txt",
        json_output_path=chunk_dir / "dialogue.json",
        state=state,
        live=live,
    )

    entities_json = process_pass(
        ollama_bin=ollama_bin,
        model=ENTITIES_MODEL,
        pass_name="entities",
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "entities_raw.txt",
        json_output_path=chunk_dir / "entities.json",
        state=state,
        live=live,
    )

    state.current_step = "building dossier input"
    if live is not None:
        live.update(render_tui(state), refresh=True)

    dossier_input = build_dossier_input(excerpt_text, entities_json, dialogue_json)
    dossier_input_path = chunk_dir / "dossier_input.txt"
    write_text(dossier_input_path, dossier_input)
    state.log(f"Wrote dossier input: {dossier_input_path}")
    if live is not None:
        live.update(render_tui(state), refresh=True)

    process_pass(
        ollama_bin=ollama_bin,
        model=DOSSIERS_MODEL,
        pass_name="dossiers",
        input_text=dossier_input,
        raw_output_path=chunk_dir / "dossiers_raw.txt",
        json_output_path=chunk_dir / "dossiers.json",
        state=state,
        live=live,
    )

    state.pass_status = "chunk complete"
    state.current_step = "finished chunk"
    state.pass_started_at = None
    state.log(f"Finished chunk: {chunk_name}")
    state.chunks_completed += 1
    if live is not None:
        live.update(render_tui(state), refresh=True)


def run_plain(args: argparse.Namespace) -> int:
    state = TUIState()
    try:
        chunk_files = collect_inputs(args)
        state.chunks_total = len(chunk_files)
        args.output_dir.mkdir(parents=True, exist_ok=True)

        for chunk_path in chunk_files:
            process_chunk(
                chunk_path=chunk_path,
                output_dir=args.output_dir,
                ollama_bin=args.ollama_bin,
                state=state,
                live=None,
            )

        print("[DONE] All chunks processed successfully.")
        return 0

    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


def main() -> int:
    args = parse_args()

    if args.no_tui:
        return run_plain(args)

    state = TUIState()

    try:
        chunk_files = collect_inputs(args)
        state.chunks_total = len(chunk_files)
        args.output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    failures: List[str] = []

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
                    )
                except Exception as exc:
                    err = f"{chunk_path.name}: {exc}"
                    failures.append(err)
                    chunk_dir = args.output_dir / chunk_path.stem
                    chunk_dir.mkdir(parents=True, exist_ok=True)
                    write_text(chunk_dir / "error.txt", err + "\n")
                    state.pass_status = "failed"
                    state.current_step = "error"
                    state.log(f"ERROR: {err}")
                    live.update(render_tui(state), refresh=True)
                time.sleep(0.2)
        finally:
            live.update(render_tui(state), refresh=True)

    if failures:
        print("[SUMMARY] Some chunks failed:", file=sys.stderr)
        for err in failures:
            print(f"- {err}", file=sys.stderr)
        return 1

    print("[DONE] All chunks processed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())