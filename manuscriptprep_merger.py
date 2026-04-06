#!/usr/bin/env python3
"""
manuscriptprep_merger.py

Merge per-chunk ManuscriptPrep outputs into book-level JSON artifacts,
with upgraded resolver logic for character/entity normalization.

Typical usage:
    python manuscriptprep_merger.py \
      --input-dir out/treasure_island \
      --output-dir merged/treasure_island

Optional:
    python manuscriptprep_merger.py \
      --input-dir out/treasure_island \
      --output-dir merged/treasure_island \
      --chunk-manifest work/manifests/treasure_island/chunk_manifest.json

Outputs:
- structure_merged.json
- dialogue_merged.json
- entities_merged.json
- dossiers_merged.json
- conflict_report.json
- merge_report.json
- book_merged.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from manuscriptprep.config import ConfigError, ManuscriptPrepConfig, load_config
from manuscriptprep.paths import build_paths

PASS_FILES = {
    "structure": "structure.json",
    "dialogue": "dialogue.json",
    "entities": "entities.json",
    "dossiers": "dossiers.json",
    "timing": "timing.json",
}

ENTITY_KEYS = ["characters", "places", "objects", "identity_notes"]

TITLE_EQUIVS = {
    "dr": "doctor",
    "dr.": "doctor",
    "doctor": "doctor",
    "mr": "mr",
    "mr.": "mr",
    "mister": "mr",
    "mrs": "mrs",
    "mrs.": "mrs",
    "missus": "mrs",
    "miss": "miss",
    "ms": "ms",
    "ms.": "ms",
    "capt": "captain",
    "capt.": "captain",
    "capn": "captain",
    "captain": "captain",
    "sir": "sir",
    "lady": "lady",
    "lord": "lord",
    "prof": "professor",
    "prof.": "professor",
    "professor": "professor",
    "rev": "reverend",
    "rev.": "reverend",
    "reverend": "reverend",
}

GENERIC_CHARACTER_WORDS = {
    "doctor",
    "captain",
    "mr",
    "mrs",
    "miss",
    "ms",
    "professor",
    "reverend",
    "sir",
    "lady",
    "lord",
    "narrator",
    "mother",
    "father",
    "boy",
    "girl",
    "man",
    "woman",
    "stranger",
    "innkeeper",
    "captain",
}

GENERIC_PREFIXES = {"the"}

ROLE_HINTS = {
    "doctor": {"doctor", "physician", "surgeon", "magistrate"},
    "captain": {"captain", "sailor", "seaman", "pirate", "buccaneer"},
    "mr": set(),
    "mrs": set(),
    "miss": set(),
    "ms": set(),
    "professor": {"professor", "teacher"},
    "reverend": {"priest", "clergyman", "reverend"},
}


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


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def norm_text(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = re.sub(r"[\"']", "", s)
    s = re.sub(r"[^a-z0-9\s_.-]", "", s)
    s = re.sub(r"[\s_-]+", " ", s)
    return s.strip()


def canonicalize_title_token(token: str) -> str:
    return TITLE_EQUIVS.get(token.lower(), token.lower())


def tokenize_name(name: str) -> List[str]:
    text = norm_text(name)
    tokens = [t for t in re.split(r"\s+", text) if t]
    return [canonicalize_title_token(t) for t in tokens]


def strip_leading_generics(tokens: List[str]) -> List[str]:
    out = list(tokens)
    while out and out[0] in GENERIC_PREFIXES:
        out = out[1:]
    return out


def parse_name_form(name: str) -> Dict[str, Any]:
    tokens = strip_leading_generics(tokenize_name(name))
    title = None
    base_tokens = list(tokens)
    if base_tokens and base_tokens[0] in TITLE_EQUIVS.values():
        title = base_tokens[0]
        base_tokens = base_tokens[1:]

    surname = base_tokens[-1] if base_tokens else None
    given = base_tokens[0] if len(base_tokens) >= 2 else None

    return {
        "original": name,
        "normalized": " ".join(tokens),
        "tokens": tokens,
        "title": title,
        "base_tokens": base_tokens,
        "surname": surname,
        "given": given,
        "is_generic": (not base_tokens and title is not None)
        or (" ".join(tokens) in GENERIC_CHARACTER_WORDS)
        or (len(tokens) == 1 and tokens[0] in GENERIC_CHARACTER_WORDS),
    }


def unique_preserve_order(values: Iterable[Any]) -> List[Any]:
    seen = set()
    out = []
    for v in values:
        key = json.dumps(v, sort_keys=True, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def nonempty_unique_strs(values: List[Any]) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for v in values:
        if isinstance(v, str):
            s = v.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
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


@dataclass
class MergerRuntimeSettings:
    input_dir: Path
    output_dir: Path
    chunk_manifest: Optional[Path]
    config_path: Optional[Path]


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


def roles_compatible(title: Optional[str], roles: List[str]) -> bool:
    if not title:
        return True
    hints = ROLE_HINTS.get(title, set())
    if not hints:
        return True
    joined = " ".join(r.lower() for r in roles)
    return any(h in joined for h in hints) or not roles


def build_dossier_candidates(chunks: List[ChunkData]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for chunk in chunks:
        djson = chunk.dossiers or {}
        dossiers = extract_dossier_list(djson)
        for dossier in dossiers:
            name = dossier.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            parsed = parse_name_form(name)
            aliases = nonempty_unique_strs(dossier.get("aliases", []))
            roles = [r for r in [dossier.get("role")] if isinstance(r, str)] + nonempty_unique_strs(dossier.get("roles", []))
            candidates.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "dossier": dossier,
                    "name": name,
                    "parsed": parsed,
                    "aliases": aliases,
                    "roles": nonempty_unique_strs(roles),
                }
            )
    return candidates


def can_merge_name_forms(a: Dict[str, Any], b: Dict[str, Any], a_roles: List[str], b_roles: List[str]) -> Tuple[bool, str, str, int]:
    pa = a
    pb = b

    # Exact normalized match
    if pa["normalized"] == pb["normalized"]:
        return True, "safe", "exact_normalized_match", 100

    # Title-normalized same base tokens
    if pa["base_tokens"] and pa["base_tokens"] == pb["base_tokens"] and pa["title"] == pb["title"]:
        return True, "safe", "same_base_tokens_and_title", 98

    # Same surname and compatible titled variants
    if pa["surname"] and pa["surname"] == pb["surname"]:
        if pa["title"] == pb["title"] and pa["title"] is not None:
            return True, "safe", "same_title_same_surname", 96
        if pa["title"] is None and pb["title"] and pa["base_tokens"] == pb["base_tokens"]:
            return True, "probable", "bare_name_matches_titled_full_name", 88
        if pb["title"] is None and pa["title"] and pa["base_tokens"] == pb["base_tokens"]:
            return True, "probable", "bare_name_matches_titled_full_name", 88
        if len(pa["base_tokens"]) == 1 and len(pb["base_tokens"]) >= 1 and pa["surname"] == pb["surname"]:
            if pa["title"] == pb["title"] and pa["title"] is not None:
                return True, "probable", "surname_only_variant_same_title", 85

    # Generic title-only to titled full name, but only when roles look compatible
    if pa["is_generic"] and pa["title"] and pb["title"] == pa["title"] and pb["surname"]:
        if roles_compatible(pa["title"], a_roles + b_roles):
            return True, "probable", "generic_title_to_single_titled_name_candidate", 78

    if pb["is_generic"] and pb["title"] and pa["title"] == pb["title"] and pa["surname"]:
        if roles_compatible(pb["title"], a_roles + b_roles):
            return True, "probable", "generic_title_to_single_titled_name_candidate", 78

    return False, "review", "no_safe_merge_rule", 0


def choose_group_label(group_items: List[Dict[str, Any]]) -> str:
    # Prefer longest titled full name, otherwise longest name
    def score(item: Dict[str, Any]) -> Tuple[int, int]:
        parsed = item["parsed"]
        titled = 1 if parsed["title"] else 0
        base_len = len(parsed["base_tokens"])
        return (titled + base_len, len(item["name"]))

    best = max(group_items, key=score)
    return best["name"]


def resolve_character_candidates(candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    groups: List[List[Dict[str, Any]]] = []
    resolution_notes: List[Dict[str, Any]] = []

    for cand in candidates:
        placed = False
        for group in groups:
            matched = False
            for existing in group:
                ok, confidence, reason, score = can_merge_name_forms(
                    cand["parsed"],
                    existing["parsed"],
                    cand["roles"],
                    existing["roles"],
                )
                if ok:
                    group.append(cand)
                    resolution_notes.append(
                        {
                            "source_name": cand["name"],
                            "target_name": existing["name"],
                            "confidence": confidence,
                            "reason": reason,
                            "score": score,
                            "chunk_id": cand["chunk_id"],
                        }
                    )
                    matched = True
                    placed = True
                    break
            if matched:
                break
        if not placed:
            groups.append([cand])

    resolved_groups: List[Dict[str, Any]] = []
    for group in groups:
        canonical_name = choose_group_label(group)
        surface_variants = unique_preserve_order([g["name"] for g in group] + [a for g in group for a in g["aliases"]])
        confidences = []
        reasons = []
        chunks = []
        for g in group:
            if g["chunk_id"] not in chunks:
                chunks.append(g["chunk_id"])
        for note in resolution_notes:
            if note["source_name"] in surface_variants and note["target_name"] in surface_variants:
                confidences.append(note["confidence"])
                reasons.append(note["reason"])
        merge_confidence = "single"
        if "safe" in confidences:
            merge_confidence = "safe"
        elif "probable" in confidences:
            merge_confidence = "probable"

        resolved_groups.append(
            {
                "canonical_name": canonical_name,
                "surface_variants": unique_preserve_order(surface_variants),
                "merge_confidence": merge_confidence,
                "merge_reasons": unique_preserve_order(reasons),
                "chunks": chunks,
                "members": group,
            }
        )

    resolved_groups = sorted(resolved_groups, key=lambda x: natural_key(x["canonical_name"]))
    return resolved_groups, resolution_notes


def merge_dossiers(chunks: List[ChunkData]) -> Dict[str, Any]:
    candidates = build_dossier_candidates(chunks)
    resolved_groups, resolution_notes = resolve_character_candidates(candidates)

    per_chunk: List[Dict[str, Any]] = []
    for chunk in chunks:
        djson = chunk.dossiers or {}
        dossiers = extract_dossier_list(djson)
        per_chunk.append({"chunk_id": chunk.chunk_id, "character_dossiers": dossiers})

    merged_list: List[Dict[str, Any]] = []

    for group in resolved_groups:
        merged = {
            "name": group["canonical_name"],
            "canonical_name": group["canonical_name"],
            "variants": [],
            "surface_variants": group["surface_variants"],
            "aliases": [],
            "roles": [],
            "biographies": [],
            "personality_traits": [],
            "vocal_notes": [],
            "accents": [],
            "spoken_dialogue_values": [],
            "identity_status_values": [],
            "chunks": group["chunks"],
            "merge_confidence": group["merge_confidence"],
            "merge_reason": unique_preserve_order(group["merge_reasons"]),
            "source_dossiers": [],
        }

        for member in group["members"]:
            dossier = member["dossier"]
            name = dossier.get("name")
            if isinstance(name, str) and name not in merged["variants"]:
                merged["variants"].append(name)

            aliases = dossier.get("aliases", [])
            if isinstance(aliases, list):
                merged["aliases"] = unique_preserve_order(merged["aliases"] + [a for a in aliases if isinstance(a, str)])

            role = dossier.get("role")
            if isinstance(role, str) and role:
                merged["roles"] = unique_preserve_order(merged["roles"] + [role])

            more_roles = dossier.get("roles", [])
            if isinstance(more_roles, list):
                merged["roles"] = unique_preserve_order(merged["roles"] + [r for r in more_roles if isinstance(r, str)])

            biography = dossier.get("biography")
            if isinstance(biography, str) and biography:
                merged["biographies"] = unique_preserve_order(merged["biographies"] + [biography])

            traits = dossier.get("personality_traits", [])
            if isinstance(traits, list):
                merged["personality_traits"] = unique_preserve_order(
                    merged["personality_traits"] + [t for t in traits if isinstance(t, str)]
                )

            vocal_notes = dossier.get("vocal_notes")
            if isinstance(vocal_notes, str) and vocal_notes:
                merged["vocal_notes"] = unique_preserve_order(merged["vocal_notes"] + [vocal_notes])

            accent = dossier.get("accent")
            if isinstance(accent, str) and accent:
                merged["accents"] = unique_preserve_order(merged["accents"] + [accent])

            spoken_dialogue = dossier.get("spoken_dialogue")
            if spoken_dialogue is not None:
                merged["spoken_dialogue_values"] = unique_preserve_order(merged["spoken_dialogue_values"] + [spoken_dialogue])

            identity_status = dossier.get("identity_status")
            if isinstance(identity_status, str) and identity_status:
                merged["identity_status_values"] = unique_preserve_order(
                    merged["identity_status_values"] + [identity_status]
                )

            merged["source_dossiers"].append({"chunk_id": member["chunk_id"], "dossier": dossier})

        merged_list.append(merged)

    return {
        "character_dossiers": merged_list,
        "per_chunk": per_chunk,
        "resolver_notes": resolution_notes,
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


def build_report(chunks: List[ChunkData], dossiers_merged: Dict[str, Any]) -> Dict[str, Any]:
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
        "resolver_merge_count": sum(1 for d in dossiers_merged.get("character_dossiers", []) if len(d.get("surface_variants", [])) > 1),
    }


def build_conflict_report(
    structure_merged: Dict[str, Any],
    dialogue_merged: Dict[str, Any],
    entities_merged: Dict[str, Any],
    dossiers_merged: Dict[str, Any],
) -> Dict[str, Any]:
    character_conflicts: List[Dict[str, Any]] = []
    entity_variant_notes: Dict[str, List[Dict[str, Any]]] = {}
    global_conflicts: List[Dict[str, Any]] = []

    for dossier in dossiers_merged.get("character_dossiers", []):
        if not isinstance(dossier, dict):
            continue

        name = dossier.get("name", "unknown")
        roles = nonempty_unique_strs(dossier.get("roles", []))
        accents = nonempty_unique_strs(dossier.get("accents", []))
        vocal_notes = nonempty_unique_strs(dossier.get("vocal_notes", []))
        identity_status_values = nonempty_unique_strs(dossier.get("identity_status_values", []))

        spoken_dialogue_values = dossier.get("spoken_dialogue_values", [])
        spoken_dialogue_unique = []
        for v in spoken_dialogue_values:
            if v not in spoken_dialogue_unique:
                spoken_dialogue_unique.append(v)

        conflicts: List[Dict[str, Any]] = []

        if len(roles) > 1:
            conflicts.append(
                {
                    "type": "role_conflict",
                    "severity": "medium",
                    "values": roles,
                    "message": f"Multiple roles observed for {name}.",
                }
            )

        if len(accents) > 1:
            conflicts.append(
                {
                    "type": "accent_conflict",
                    "severity": "high",
                    "values": accents,
                    "message": f"Multiple accent recommendations observed for {name}.",
                }
            )

        if len(spoken_dialogue_unique) > 1:
            conflicts.append(
                {
                    "type": "spoken_dialogue_conflict",
                    "severity": "high",
                    "values": spoken_dialogue_unique,
                    "message": f"Conflicting spoken_dialogue values observed for {name}.",
                }
            )

        if len(identity_status_values) > 1:
            conflicts.append(
                {
                    "type": "identity_status_conflict",
                    "severity": "medium",
                    "values": identity_status_values,
                    "message": f"Multiple identity_status values observed for {name}.",
                }
            )

        if len(vocal_notes) > 2:
            conflicts.append(
                {
                    "type": "vocal_notes_drift",
                    "severity": "low",
                    "values": vocal_notes,
                    "message": f"Many vocal note variants observed for {name}.",
                }
            )

        if conflicts:
            character_conflicts.append(
                {
                    "name": name,
                    "variants": dossier.get("variants", []),
                    "surface_variants": dossier.get("surface_variants", []),
                    "chunks": dossier.get("chunks", []),
                    "merge_confidence": dossier.get("merge_confidence"),
                    "conflicts": conflicts,
                }
            )

    for key in ["characters_normalized", "places_normalized", "objects_normalized", "identity_notes_normalized"]:
        items = entities_merged.get(key, [])
        notes: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            variants = item.get("variants", [])
            if isinstance(variants, list) and len(variants) > 1:
                notes.append(
                    {
                        "canonical": item.get("canonical"),
                        "variants": variants,
                        "chunks": item.get("chunks", []),
                        "message": f"Multiple surface variants map to {item.get('canonical')}.",
                    }
                )
        entity_variant_notes[key] = notes

    pov_values = dialogue_merged.get("observed_pov_values", [])
    if isinstance(pov_values, list) and len(pov_values) > 1:
        global_conflicts.append(
            {
                "type": "multiple_pov_values",
                "severity": "medium",
                "values": pov_values,
                "message": "Multiple POV values were observed across chunks.",
            }
        )

    statuses = structure_merged.get("statuses", [])
    nonempty_statuses = []
    for s in statuses:
        if isinstance(s, dict):
            val = s.get("status")
            if isinstance(val, str) and val.strip():
                nonempty_statuses.append(val.strip())

    unique_statuses = nonempty_unique_strs(nonempty_statuses)
    if len(unique_statuses) > 1:
        global_conflicts.append(
            {
                "type": "structure_status_variation",
                "severity": "low",
                "values": unique_statuses,
                "message": "Multiple structure status values were observed across chunks.",
            }
        )

    total_entity_variant_notes = sum(len(v) for v in entity_variant_notes.values())

    return {
        "summary": {
            "character_conflict_count": len(character_conflicts),
            "entity_variant_note_count": total_entity_variant_notes,
            "global_conflict_count": len(global_conflicts),
        },
        "character_conflicts": character_conflicts,
        "entity_variant_notes": entity_variant_notes,
        "global_conflicts": global_conflicts,
        "resolver_notes": dossiers_merged.get("resolver_notes", []),
    }


def resolve_merger_settings(args: argparse.Namespace, cfg: Optional[ManuscriptPrepConfig]) -> MergerRuntimeSettings:
    if cfg is None:
        if args.input_dir is None or args.output_dir is None:
            raise ConfigError("Missing required --input-dir or --output-dir. Provide both, or use --config with --book-slug.")
        return MergerRuntimeSettings(
            input_dir=args.input_dir.expanduser(),
            output_dir=args.output_dir.expanduser(),
            chunk_manifest=args.chunk_manifest.expanduser() if args.chunk_manifest is not None else None,
            config_path=None,
        )

    paths = build_paths(cfg)
    input_dir = args.input_dir.expanduser() if args.input_dir is not None else None
    output_dir = args.output_dir.expanduser() if args.output_dir is not None else None

    if input_dir is None or output_dir is None:
        if not args.book_slug:
            raise ConfigError(
                "When using --config without explicit --input-dir and --output-dir, provide --book-slug."
            )
        slug = args.book_slug
        input_dir = input_dir or (paths.output_root / slug)
        output_dir = output_dir or (paths.merged_root / slug)

    chunk_manifest = args.chunk_manifest.expanduser() if args.chunk_manifest is not None else None
    if chunk_manifest is None and args.book_slug:
        chunk_manifest = paths.workspace_root / "manifests" / args.book_slug / "chunk_manifest.json"

    return MergerRuntimeSettings(
        input_dir=input_dir,
        output_dir=output_dir,
        chunk_manifest=chunk_manifest,
        config_path=cfg.path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge ManuscriptPrep per-chunk outputs into book-level JSON.")
    parser.add_argument("--config", type=Path, default=None, help="Optional YAML config file")
    parser.add_argument("--book-slug", default=None, help="Book slug used to derive config-based paths")
    parser.add_argument("--input-dir", type=Path, required=False, help="Chunk output directory, e.g. out/treasure_island")
    parser.add_argument("--output-dir", type=Path, required=False, help="Destination for merged outputs")
    parser.add_argument(
        "--chunk-manifest",
        type=Path,
        default=None,
        help="Optional chunk_manifest.json from ingest for provenance and ordering hints",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        cfg = load_config(args.config) if args.config is not None else None
        settings = resolve_merger_settings(args, cfg)
    except (ConfigError, RuntimeError) as exc:
        raise SystemExit(str(exc))

    if not settings.input_dir.is_dir():
        raise SystemExit(f"Input dir does not exist: {settings.input_dir}")

    manifest, manifest_map = load_chunk_manifest(settings.chunk_manifest)
    chunk_dirs = find_chunk_dirs(settings.input_dir)
    if not chunk_dirs:
        raise SystemExit(f"No chunk directories found in {settings.input_dir}")

    chunks = [load_chunk_data(chunk_dir, manifest_map) for chunk_dir in chunk_dirs]

    structure_merged = merge_structure(chunks)
    dialogue_merged = merge_dialogue(chunks)
    entities_merged = merge_entities(chunks)
    dossiers_merged = merge_dossiers(chunks)
    timing_summary = summarize_timings(chunks)
    report = build_report(chunks, dossiers_merged)
    conflict_report = build_conflict_report(
        structure_merged=structure_merged,
        dialogue_merged=dialogue_merged,
        entities_merged=entities_merged,
        dossiers_merged=dossiers_merged,
    )

    book_slug = settings.input_dir.name
    book_title = manifest.get("book_title") if manifest else None

    book_merged = {
        "book_slug": book_slug,
        "book_title": book_title,
        "source_chunk_manifest": str(settings.chunk_manifest) if settings.chunk_manifest else None,
        "config_path": str(settings.config_path.resolve()) if settings.config_path is not None else None,
        "merge_report": report,
        "timing_summary": timing_summary,
        "conflict_report": conflict_report,
        "structure": structure_merged,
        "dialogue": dialogue_merged,
        "entities": entities_merged,
        "dossiers": dossiers_merged,
    }

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(settings.output_dir / "structure_merged.json", structure_merged)
    write_json(settings.output_dir / "dialogue_merged.json", dialogue_merged)
    write_json(settings.output_dir / "entities_merged.json", entities_merged)
    write_json(settings.output_dir / "dossiers_merged.json", dossiers_merged)
    write_json(settings.output_dir / "conflict_report.json", conflict_report)
    write_json(settings.output_dir / "merge_report.json", report)
    write_json(settings.output_dir / "book_merged.json", book_merged)

    print(f"Merged {len(chunks)} chunks from {settings.input_dir}")
    print(f"Wrote merged outputs to {settings.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
