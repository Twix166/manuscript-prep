#!/usr/bin/env python3
"""
manuscriptprep_merger.py

Merge per-chunk ManuscriptPrep outputs into book-level JSON artifacts.

Typical usage:
    python manuscriptprep_merger.py \
      --input-dir out/treasure_island \
      --output-dir merged/treasure_island

Optional:
    python manuscriptprep_merger.py \
      --input-dir out/treasure_island \
      --output-dir merged/treasure_island \
      --chunk-manifest work/manifests/treasure_island/chunk_manifest.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PASS_FILES = {
    "structure": "structure.json",
    "dialogue": "dialogue.json",
    "entities": "entities.json",
    "dossiers": "dossiers.json",
    "timing": "timing.json",
}

ENTITY_KEYS = ["characters", "places", "objects", "identity_notes"]


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def natural_key(name: str) -> List[Any]:
    parts = re.split(r"(\d+)", name)
    out: List[Any] = []
    for p in parts:
        if p.isdigit():
            out.append(int(p))
        else:
            out.append(p.lower())
    return out


def norm_text(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[\"'`]", "", s)
    s = re.sub(r"[^a-z0-9\s_-]", "", s)
    s = re.sub(r"[\s_-]+", " ", s)
    return s.strip()


def unique_preserve_order(values: Iterable[Any]) -> List[Any]:
    seen = set()
    out = []
    for v in values:
        key = json.dumps(v, sort_keys=True, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


@dataclass
class ChunkData:
    chunk_id: str
    chunk_dir: Path
    structure: Optional[Dict[str, Any]]
    dialogue: Optional[Dict[str, Any]]
    entities: Optional[Dict[str, Any]]
    dossiers: Optional[Dict[str, Any]]
    timing: Optional[Dict[str, Any]]
    chunk_manifest_entry: Optional[Dict[str, Any]] = None


def find_chunk_dirs(input_dir: Path) -> List[Path]:
    chunks = [p for p in input_dir.iterdir() if p.is_dir() and p.name.startswith("chunk_")]
    return sorted(chunks, key=lambda p: natural_key(p.name))


def load_chunk_manifest(path: Optional[Path]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    if path is None or not path.exists():
        return None, {}
    manifest = read_json(path)
    mapping: Dict[str, Dict[str, Any]] = {}
    for item in manifest.get("chunks", []):
        chunk_id = item.get("chunk_id")
        if chunk_id:
            mapping[chunk_id] = item
    return manifest, mapping


def load_chunk_data(chunk_dir: Path, manifest_map: Dict[str, Dict[str, Any]]) -> ChunkData:
    chunk_id = chunk_dir.name

    def maybe_load(pass_name: str) -> Optional[Dict[str, Any]]:
        path = chunk_dir / PASS_FILES[pass_name]
        if path.exists():
            try:
                return read_json(path)
            except Exception:
                return {"_load_error": f"Could not parse {path.name}"}
        return None

    return ChunkData(
        chunk_id=chunk_id,
        chunk_dir=chunk_dir,
        structure=maybe_load("structure"),
        dialogue=maybe_load("dialogue"),
        entities=maybe_load("entities"),
        dossiers=maybe_load("dossiers"),
        timing=maybe_load("timing"),
        chunk_manifest_entry=manifest_map.get(chunk_id),
    )


def merge_structure(chunks: List[ChunkData]) -> Dict[str, Any]:
    chapters: List[str] = []
    parts: List[str] = []
    scene_breaks: List[Any] = []
    statuses: List[Dict[str, Any]] = []
    per_chunk: List[Dict[str, Any]] = []

    for chunk in chunks:
        data = chunk.structure or {}
        c_chapters = data.get("chapters", []) or data.get("chapter_titles", [])
        c_parts = data.get("parts", []) or data.get("part_divisions", [])
        c_scene_breaks = data.get("scene_breaks", [])
        c_status = data.get("status", "")

        if isinstance(c_chapters, list):
            chapters.extend([x for x in c_chapters if isinstance(x, str)])
        if isinstance(c_parts, list):
            parts.extend([x for x in c_parts if isinstance(x, str)])
        if isinstance(c_scene_breaks, list):
            scene_breaks.extend(c_scene_breaks)

        statuses.append({"chunk_id": chunk.chunk_id, "status": c_status})
        per_chunk.append(
            {
                "chunk_id": chunk.chunk_id,
                "chapters": c_chapters if isinstance(c_chapters, list) else [],
                "parts": c_parts if isinstance(c_parts, list) else [],
                "scene_breaks": c_scene_breaks if isinstance(c_scene_breaks, list) else [],
                "status": c_status,
            }
        )

    return {
        "chapters": unique_preserve_order(chapters),
        "parts": unique_preserve_order(parts),
        "scene_breaks": unique_preserve_order(scene_breaks),
        "per_chunk": per_chunk,
        "statuses": statuses,
    }


def merge_dialogue(chunks: List[ChunkData]) -> Dict[str, Any]:
    pov_values: List[str] = []
    attributed_speakers: List[str] = []
    per_chunk: List[Dict[str, Any]] = []

    dialogue_chunks = 0
    internal_thought_chunks = 0
    unattributed_dialogue_chunks = 0

    for chunk in chunks:
        data = chunk.dialogue or {}
        pov = data.get("pov")
        dialogue_present = bool(data.get("dialogue", False))
        internal_thought = bool(data.get("internal_thought", False))
        speakers = data.get("explicitly_attributed_speakers", [])
        unattributed = bool(data.get("unattributed_dialogue_present", False))

        if isinstance(pov, str) and pov:
            pov_values.append(pov)
        if isinstance(speakers, list):
            attributed_speakers.extend([s for s in speakers if isinstance(s, str)])

        if dialogue_present:
            dialogue_chunks += 1
        if internal_thought:
            internal_thought_chunks += 1
        if unattributed:
            unattributed_dialogue_chunks += 1

        per_chunk.append(
            {
                "chunk_id": chunk.chunk_id,
                "pov": pov,
                "dialogue": dialogue_present,
                "internal_thought": internal_thought,
                "explicitly_attributed_speakers": speakers if isinstance(speakers, list) else [],
                "unattributed_dialogue_present": unattributed,
            }
        )

    dominant_pov = None
    if pov_values:
        counts: Dict[str, int] = defaultdict(int)
        for p in pov_values:
            counts[p] += 1
        dominant_pov = max(counts.items(), key=lambda x: x[1])[0]

    return {
        "dominant_pov": dominant_pov,
        "observed_pov_values": unique_preserve_order(pov_values),
        "dialogue_present_in_chunks": dialogue_chunks,
        "internal_thought_present_in_chunks": internal_thought_chunks,
        "unattributed_dialogue_present_in_chunks": unattributed_dialogue_chunks,
        "explicitly_attributed_speakers": unique_preserve_order(attributed_speakers),
        "per_chunk": per_chunk,
    }


def merge_entities(chunks: List[ChunkData]) -> Dict[str, Any]:
    exact_sets: Dict[str, List[str]] = {k: [] for k in ENTITY_KEYS}
    normalized_maps: Dict[str, Dict[str, Dict[str, Any]]] = {k: {} for k in ENTITY_KEYS}
    per_chunk: List[Dict[str, Any]] = []

    for chunk in chunks:
        data = chunk.entities or {}
        chunk_record: Dict[str, Any] = {"chunk_id": chunk.chunk_id}

        for key in ENTITY_KEYS:
            values = data.get(key, [])
            if not isinstance(values, list):
                values = []
            chunk_record[key] = values
            for value in values:
                if not isinstance(value, str):
                    continue
                exact_sets[key].append(value)
                n = norm_text(value)
                if not n:
                    continue
                rec = normalized_maps[key].setdefault(
                    n,
                    {
                        "canonical": value,
                        "variants": [],
                        "chunks": [],
                    },
                )
                if value not in rec["variants"]:
                    rec["variants"].append(value)
                if chunk.chunk_id not in rec["chunks"]:
                    rec["chunks"].append(chunk.chunk_id)

        per_chunk.append(chunk_record)

    merged: Dict[str, Any] = {"per_chunk": per_chunk}
    for key in ENTITY_KEYS:
        merged[key] = unique_preserve_order(exact_sets[key])
        merged[f"{key}_normalized"] = sorted(
            normalized_maps[key].values(),
            key=lambda x: natural_key(x["canonical"]),
        )
    return merged


def extract_dossier_list(dossier_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not dossier_json:
        return []
    if isinstance(dossier_json.get("character_dossiers"), list):
        return [x for x in dossier_json["character_dossiers"] if isinstance(x, dict)]
    if isinstance(dossier_json.get("dossiers"), list):
        return [x for x in dossier_json["dossiers"] if isinstance(x, dict)]
    return []


def merge_dossiers(chunks: List[ChunkData]) -> Dict[str, Any]:
    merged_map: Dict[str, Dict[str, Any]] = {}
    per_chunk: List[Dict[str, Any]] = []

    for chunk in chunks:
        djson = chunk.dossiers or {}
        dossiers = extract_dossier_list(djson)
        per_chunk.append({"chunk_id": chunk.chunk_id, "character_dossiers": dossiers})

        for dossier in dossiers:
            name = dossier.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            key = norm_text(name)
            if not key:
                continue

            rec = merged_map.setdefault(
                key,
                {
                    "name": name,
                    "variants": [],
                    "aliases": [],
                    "roles": [],
                    "biographies": [],
                    "personality_traits": [],
                    "vocal_notes": [],
                    "accents": [],
                    "spoken_dialogue_values": [],
                    "identity_status_values": [],
                    "chunks": [],
                    "source_dossiers": [],
                },
            )

            if name not in rec["variants"]:
                rec["variants"].append(name)

            aliases = dossier.get("aliases", [])
            if isinstance(aliases, list):
                rec["aliases"] = unique_preserve_order(rec["aliases"] + [a for a in aliases if isinstance(a, str)])

            role = dossier.get("role")
            if isinstance(role, str) and role:
                rec["roles"] = unique_preserve_order(rec["roles"] + [role])

            biography = dossier.get("biography")
            if isinstance(biography, str) and biography:
                rec["biographies"] = unique_preserve_order(rec["biographies"] + [biography])

            traits = dossier.get("personality_traits", [])
            if isinstance(traits, list):
                rec["personality_traits"] = unique_preserve_order(
                    rec["personality_traits"] + [t for t in traits if isinstance(t, str)]
                )

            vocal_notes = dossier.get("vocal_notes")
            if isinstance(vocal_notes, str) and vocal_notes:
                rec["vocal_notes"] = unique_preserve_order(rec["vocal_notes"] + [vocal_notes])

            accent = dossier.get("accent")
            if isinstance(accent, str) and accent:
                rec["accents"] = unique_preserve_order(rec["accents"] + [accent])

            spoken_dialogue = dossier.get("spoken_dialogue")
            if spoken_dialogue is not None:
                rec["spoken_dialogue_values"] = unique_preserve_order(rec["spoken_dialogue_values"] + [spoken_dialogue])

            identity_status = dossier.get("identity_status")
            if isinstance(identity_status, str) and identity_status:
                rec["identity_status_values"] = unique_preserve_order(
                    rec["identity_status_values"] + [identity_status]
                )

            if chunk.chunk_id not in rec["chunks"]:
                rec["chunks"].append(chunk.chunk_id)

            rec["source_dossiers"].append({"chunk_id": chunk.chunk_id, "dossier": dossier})

    merged_list = sorted(merged_map.values(), key=lambda x: natural_key(x["name"]))
    return {
        "character_dossiers": merged_list,
        "per_chunk": per_chunk,
    }


def summarize_timings(chunks: List[ChunkData]) -> Dict[str, Any]:
    total_book_seconds = 0.0
    pass_totals: Dict[str, float] = defaultdict(float)
    per_chunk: List[Dict[str, Any]] = []

    for chunk in chunks:
        t = chunk.timing or {}
        total = t.get("total_duration_seconds")
        passes = t.get("passes", {})
        if isinstance(total, (int, float)):
            total_book_seconds += float(total)

        if isinstance(passes, dict):
            for name, value in passes.items():
                if isinstance(value, (int, float)):
                    pass_totals[name] += float(value)

        per_chunk.append(
            {
                "chunk_id": chunk.chunk_id,
                "total_duration_seconds": total,
                "passes": passes if isinstance(passes, dict) else {},
            }
        )

    return {
        "book_total_duration_seconds": round(total_book_seconds, 3),
        "pass_total_duration_seconds": {k: round(v, 3) for k, v in pass_totals.items()},
        "per_chunk": per_chunk,
    }


def build_report(chunks: List[ChunkData]) -> Dict[str, Any]:
    missing: Dict[str, List[str]] = defaultdict(list)
    present_counts: Dict[str, int] = defaultdict(int)

    for chunk in chunks:
        for pass_name in ["structure", "dialogue", "entities", "dossiers", "timing"]:
            if getattr(chunk, pass_name) is None:
                missing[pass_name].append(chunk.chunk_id)
            else:
                present_counts[pass_name] += 1

    return {
        "chunk_count": len(chunks),
        "present_counts": dict(present_counts),
        "missing": dict(missing),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge ManuscriptPrep per-chunk outputs into book-level JSON.")
    parser.add_argument("--input-dir", type=Path, required=True, help="Chunk output directory, e.g. out/treasure_island")
    parser.add_argument("--output-dir", type=Path, required=True, help="Destination for merged outputs")
    parser.add_argument(
        "--chunk-manifest",
        type=Path,
        default=None,
        help="Optional chunk_manifest.json from ingest for provenance and ordering hints",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input_dir.is_dir():
        raise SystemExit(f"Input dir does not exist: {args.input_dir}")

    manifest, manifest_map = load_chunk_manifest(args.chunk_manifest)
    chunk_dirs = find_chunk_dirs(args.input_dir)
    if not chunk_dirs:
        raise SystemExit(f"No chunk directories found in {args.input_dir}")

    chunks = [load_chunk_data(chunk_dir, manifest_map) for chunk_dir in chunk_dirs]

    structure_merged = merge_structure(chunks)
    dialogue_merged = merge_dialogue(chunks)
    entities_merged = merge_entities(chunks)
    dossiers_merged = merge_dossiers(chunks)
    timing_summary = summarize_timings(chunks)
    report = build_report(chunks)

    book_slug = args.input_dir.name
    book_title = manifest.get("book_title") if manifest else None

    book_merged = {
        "book_slug": book_slug,
        "book_title": book_title,
        "source_chunk_manifest": str(args.chunk_manifest) if args.chunk_manifest else None,
        "merge_report": report,
        "timing_summary": timing_summary,
        "structure": structure_merged,
        "dialogue": dialogue_merged,
        "entities": entities_merged,
        "dossiers": dossiers_merged,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "structure_merged.json", structure_merged)
    write_json(args.output_dir / "dialogue_merged.json", dialogue_merged)
    write_json(args.output_dir / "entities_merged.json", entities_merged)
    write_json(args.output_dir / "dossiers_merged.json", dossiers_merged)
    write_json(args.output_dir / "merge_report.json", report)
    write_json(args.output_dir / "book_merged.json", book_merged)

    print(f"Merged {len(chunks)} chunks from {args.input_dir}")
    print(f"Wrote merged outputs to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())