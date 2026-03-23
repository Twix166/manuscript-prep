#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


STRUCTURE_MODEL = "manuscriptprep-structure"
DIALOGUE_MODEL = "manuscriptprep-dialogue"
ENTITIES_MODEL = "manuscriptprep-entities"
DOSSIERS_MODEL = "manuscriptprep-dossiers"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multi-pass manuscript analysis via Ollama.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", type=Path, help="Single chunk text file")
    group.add_argument("--input-dir", type=Path, help="Directory containing chunk text files")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for outputs")
    parser.add_argument("--ollama-bin", default="ollama", help="Path to ollama binary")
    parser.add_argument("--glob", default="*.txt", help="Glob for input-dir mode")
    return parser.parse_args()


def run_ollama(ollama_bin: str, model: str, prompt_text: str) -> str:
    result = subprocess.run(
        [ollama_bin, "run", model],
        input=prompt_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Ollama failed for model '{model}'.\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
    output = result.stdout.strip()
    if not output:
        raise RuntimeError(f"Empty output from model '{model}'")
    return output


def extract_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(f"Model output is not valid JSON:\n{text}")
        snippet = text[start:end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Model output is not valid JSON:\n{text}") from exc


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def process_pass(
    *,
    ollama_bin: str,
    model: str,
    input_text: str,
    raw_output_path: Path,
    json_output_path: Path,
) -> Dict[str, Any]:
    raw = run_ollama(ollama_bin, model, input_text)
    write_text(raw_output_path, raw + "\n")
    parsed = extract_json(raw)
    write_json(json_output_path, parsed)
    return parsed


def process_chunk(chunk_path: Path, output_dir: Path, ollama_bin: str) -> None:
    chunk_name = chunk_path.stem
    excerpt_text = read_text(chunk_path)
    chunk_dir = output_dir / chunk_name
    chunk_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Processing {chunk_path.name}")

    # Structure
    structure_json = process_pass(
        ollama_bin=ollama_bin,
        model=STRUCTURE_MODEL,
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "structure_raw.txt",
        json_output_path=chunk_dir / "structure.json",
    )
    print("[OK]   structure")

    # Dialogue
    dialogue_json = process_pass(
        ollama_bin=ollama_bin,
        model=DIALOGUE_MODEL,
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "dialogue_raw.txt",
        json_output_path=chunk_dir / "dialogue.json",
    )
    print("[OK]   dialogue")

    # Entities
    entities_json = process_pass(
        ollama_bin=ollama_bin,
        model=ENTITIES_MODEL,
        input_text=excerpt_text,
        raw_output_path=chunk_dir / "entities_raw.txt",
        json_output_path=chunk_dir / "entities.json",
    )
    print("[OK]   entities")

    # Dossiers
    dossier_input = build_dossier_input(excerpt_text, entities_json, dialogue_json)
    write_text(chunk_dir / "dossier_input.txt", dossier_input)

    process_pass(
        ollama_bin=ollama_bin,
        model=DOSSIERS_MODEL,
        input_text=dossier_input,
        raw_output_path=chunk_dir / "dossiers_raw.txt",
        json_output_path=chunk_dir / "dossiers.json",
    )
    print("[OK]   dossiers")


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        chunk_files = collect_inputs(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    failures = []

    for chunk_path in chunk_files:
        try:
            process_chunk(chunk_path, args.output_dir, args.ollama_bin)
        except Exception as exc:
            failures.append((chunk_path.name, str(exc)))
            error_dir = args.output_dir / chunk_path.stem
            error_dir.mkdir(parents=True, exist_ok=True)
            write_text(error_dir / "error.txt", str(exc) + "\n")
            print(f"[ERROR] {chunk_path.name}: {exc}", file=sys.stderr)

    if failures:
        print("\n[SUMMARY] Some chunks failed:", file=sys.stderr)
        for name, err in failures:
            print(f"- {name}: {err}", file=sys.stderr)
        return 1

    print("[DONE] All chunks processed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
