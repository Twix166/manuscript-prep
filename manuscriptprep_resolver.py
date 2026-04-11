#!/usr/bin/env python3
"""
manuscriptprep_resolver.py

Book-level LLM-assisted resolver for ManuscriptPrep.

Purpose
-------
Takes merged book outputs and asks a local Ollama model to reconcile
likely character/entity variants into canonical identities.

This is a HYBRID resolver:
1. deterministic candidate grouping
2. LLM review of ambiguous / mergeable groups
3. resolved output artifacts

Expected input directory
------------------------
A merged book directory containing:
- book_merged.json
- entities_merged.json
- dossiers_merged.json
- conflict_report.json
- dialogue_merged.json (optional)

Typical usage
-------------
python manuscriptprep_resolver.py \
  --input-dir merged/treasure_island \
  --output-dir resolved/treasure_island \
  --model manuscriptprep-resolver

Optional:
python manuscriptprep_resolver.py \
  --input-dir merged/treasure_island \
  --output-dir resolved/treasure_island \
  --model qwen3:8b-q4_K_M \
  --max-group-size 8 \
  --min-variant-count 2

Outputs
-------
- resolution_candidates.json
- resolution_map.json
- resolution_report.json
- book_resolved.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from manuscriptprep.config import ConfigError, ManuscriptPrepConfig, load_config
from manuscriptprep.paths import build_paths
from manuscriptprep.runtime_logging import emit_runtime_event

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
    "squire": "squire",
}

GENERIC_CHARACTER_WORDS = {
    "doctor", "captain", "mr", "mrs", "miss", "ms", "professor", "reverend",
    "sir", "lady", "lord", "narrator", "mother", "father", "boy", "girl",
    "man", "woman", "stranger", "innkeeper", "squire",
}

GENERIC_PREFIXES = {"the"}

SYSTEM_PROMPT = """You are ManuscriptPrepResolver, a conservative book-level identity resolver for fiction manuscripts.

Task:
Given a candidate group of possibly related character mentions from a single book, decide which mentions should merge into a single canonical character identity.

Rules:
- Be conservative.
- Prefer under-merging to over-merging.
- Merge obvious title/name variants:
  - Dr. Livesey / Doctor Livesey
  - Jim / Jim Hawkins
  - Silver / Long John Silver
only when the evidence supports it.
- Do NOT merge generic role words like "captain" or "doctor" unless the evidence strongly indicates a single character.
- Use the provided roles, dossier evidence, chunks, and conflict notes.
- Output VALID JSON ONLY.
- No markdown.
- No explanation outside JSON.

Required JSON schema:
{
  "canonical_name": "string",
  "merge": true,
  "confidence": "safe|probable|review|do_not_merge",
  "members_to_merge": ["string", "..."],
  "members_to_keep_separate": ["string", "..."],
  "reasons": ["string", "..."]
}

If the group should NOT be merged, set:
- "merge": false
- "confidence": "do_not_merge" or "review"
- "canonical_name": ""
"""


@dataclass
class ResolverRuntimeSettings:
    input_dir: Path
    output_dir: Path
    model: str
    timeout: int
    min_variant_count: int
    max_group_size: int
    config_path: Optional[Path]

def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

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
    out = []
    seen = set()
    for v in values:
        if isinstance(v, str):
            s = v.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out

def natural_key(name: str) -> List[Any]:
    parts = re.split(r"(\d+)", name)
    out = []
    for p in parts:
        out.append(int(p) if p.isdigit() else p.lower())
    return out

def build_character_pool(book_merged: Dict[str, Any], entities: Dict[str, Any], dossiers: Dict[str, Any], conflict_report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    pool: Dict[str, Dict[str, Any]] = {}

    def ensure(name: str) -> Dict[str, Any]:
        key = norm_text(name)
        rec = pool.setdefault(
            key,
            {
                "name": name,
                "normalized": key,
                "parsed": parse_name_form(name),
                "sources": [],
                "roles": [],
                "chunks": [],
                "variants": [],
                "accents": [],
                "notes": [],
            },
        )
        if name not in rec["variants"]:
            rec["variants"].append(name)
        return rec

    # Entity characters
    for name in entities.get("characters", []):
        if isinstance(name, str) and name.strip():
            rec = ensure(name)
            rec["sources"].append("entities")

    for item in entities.get("characters_normalized", []):
        if isinstance(item, dict):
            canonical = item.get("canonical")
            if isinstance(canonical, str) and canonical.strip():
                rec = ensure(canonical)
                rec["sources"].append("entities_normalized")
                rec["variants"] = unique_preserve_order(rec["variants"] + [v for v in item.get("variants", []) if isinstance(v, str)])
                rec["chunks"] = unique_preserve_order(rec["chunks"] + [c for c in item.get("chunks", []) if isinstance(c, str)])

    # Dialogue speakers
    dialogue = book_merged.get("dialogue", {})
    for speaker in dialogue.get("explicitly_attributed_speakers", []):
        if isinstance(speaker, str) and speaker.strip():
            rec = ensure(speaker)
            rec["sources"].append("dialogue")

    # Dossiers
    for dossier in dossiers.get("character_dossiers", []):
        if not isinstance(dossier, dict):
            continue
        name = dossier.get("name")
        if isinstance(name, str) and name.strip():
            rec = ensure(name)
            rec["sources"].append("dossiers")
            rec["roles"] = unique_preserve_order(rec["roles"] + [r for r in dossier.get("roles", []) if isinstance(r, str)])
            rec["chunks"] = unique_preserve_order(rec["chunks"] + [c for c in dossier.get("chunks", []) if isinstance(c, str)])
            rec["variants"] = unique_preserve_order(rec["variants"] + [v for v in dossier.get("variants", []) if isinstance(v, str)])
            rec["variants"] = unique_preserve_order(rec["variants"] + [v for v in dossier.get("surface_variants", []) if isinstance(v, str)])
            rec["accents"] = unique_preserve_order(rec["accents"] + [a for a in dossier.get("accents", []) if isinstance(a, str)])

    # Conflict report names
    for cc in conflict_report.get("character_conflicts", []):
        if not isinstance(cc, dict):
            continue
        name = cc.get("name")
        if isinstance(name, str) and name.strip():
            rec = ensure(name)
            rec["sources"].append("conflict_report")
            rec["chunks"] = unique_preserve_order(rec["chunks"] + [c for c in cc.get("chunks", []) if isinstance(c, str)])
            rec["variants"] = unique_preserve_order(rec["variants"] + [v for v in cc.get("variants", []) if isinstance(v, str)])
            rec["variants"] = unique_preserve_order(rec["variants"] + [v for v in cc.get("surface_variants", []) if isinstance(v, str)])

    return pool

def score_pair(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[int, List[str]]:
    pa = a["parsed"]
    pb = b["parsed"]
    score = 0
    reasons: List[str] = []

    if pa["normalized"] == pb["normalized"]:
        score += 100
        reasons.append("exact_normalized_match")

    if pa["base_tokens"] and pa["base_tokens"] == pb["base_tokens"] and pa["title"] == pb["title"]:
        score += 95
        reasons.append("same_base_tokens_and_title")

    if pa["surname"] and pb["surname"] and pa["surname"] == pb["surname"]:
        score += 40
        reasons.append("same_surname")

    if pa["title"] and pb["title"] and pa["title"] == pb["title"]:
        score += 20
        reasons.append("same_title")

    if pa["given"] and pb["given"] and pa["given"] == pb["given"]:
        score += 15
        reasons.append("same_given_name")

    if pa["is_generic"] and pb["title"] and pa["title"] == pb["title"]:
        score += 22
        reasons.append("generic_title_to_titled_name")
    if pb["is_generic"] and pa["title"] and pa["title"] == pb["title"]:
        score += 22
        reasons.append("generic_title_to_titled_name")

    # overlap in chunks
    overlap = set(a.get("chunks", [])) & set(b.get("chunks", []))
    if overlap:
        score += min(20, 4 * len(overlap))
        reasons.append("chunk_overlap")

    # overlap in roles
    roles_a = {r.lower() for r in a.get("roles", [])}
    roles_b = {r.lower() for r in b.get("roles", [])}
    if roles_a & roles_b:
        score += 12
        reasons.append("role_overlap")

    # variants directly overlap after normalization
    variants_a = {norm_text(v) for v in a.get("variants", [])}
    variants_b = {norm_text(v) for v in b.get("variants", [])}
    if variants_a & variants_b:
        score += 50
        reasons.append("variant_overlap")

    return score, reasons

def cluster_candidates(pool: Dict[str, Dict[str, Any]], min_variant_count: int, max_group_size: int) -> List[Dict[str, Any]]:
    items = sorted(pool.values(), key=lambda x: natural_key(x["name"]))
    used = set()
    groups = []

    for i, a in enumerate(items):
        if i in used:
            continue
        group = [a]
        group_reasons: Dict[str, List[str]] = {a["name"]: []}

        for j, b in enumerate(items):
            if i == j or j in used:
                continue
            score, reasons = score_pair(a, b)
            if score >= 45:
                group.append(b)
                group_reasons[b["name"]] = reasons

        if len(group) >= min_variant_count:
            group = sorted(group, key=lambda x: natural_key(x["name"]))[:max_group_size]
            for g in group:
                idx = items.index(g)
                used.add(idx)
            groups.append(
                {
                    "group_id": f"group_{len(groups):03d}",
                    "members": [g["name"] for g in group],
                    "member_records": group,
                    "pairing_reasons": group_reasons,
                }
            )

    return groups

def choose_canonical_name_from_response(response: Dict[str, Any], group: Dict[str, Any]) -> str:
    name = response.get("canonical_name")
    if isinstance(name, str) and name.strip():
        return name.strip()

    # fallback: prefer longest titled name
    def score(rec: Dict[str, Any]) -> Tuple[int, int]:
        p = rec["parsed"]
        return ((1 if p["title"] else 0) + len(p["base_tokens"]), len(rec["name"]))

    return max(group["member_records"], key=score)["name"]

def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("Could not parse JSON from model output")

def ask_ollama(model: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    cmd = ["ollama", "run", model]
    proc = subprocess.run(
        cmd,
        input=f"{SYSTEM_PROMPT}\n\n{prompt}",
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Ollama returned {proc.returncode}: {proc.stderr.strip()}")
    return extract_json_object(proc.stdout)

def resolve_groups_with_llm(groups: List[Dict[str, Any]], model: str, timeout: int) -> List[Dict[str, Any]]:
    results = []
    total_groups = len(groups)
    for index, group in enumerate(groups, start=1):
        emit_runtime_event(
            "manuscriptprep-resolver",
            "resolve_group_start",
            group_id=group["group_id"],
            group_index=index,
            total_groups=total_groups,
            candidate_names=group["members"],
            model=model,
        )
        payload = {
            "group_id": group["group_id"],
            "members": [
                {
                    "name": rec["name"],
                    "normalized": rec["normalized"],
                    "title": rec["parsed"]["title"],
                    "surname": rec["parsed"]["surname"],
                    "given": rec["parsed"]["given"],
                    "is_generic": rec["parsed"]["is_generic"],
                    "roles": rec.get("roles", []),
                    "chunks": rec.get("chunks", []),
                    "variants": rec.get("variants", []),
                    "accents": rec.get("accents", []),
                    "sources": rec.get("sources", []),
                }
                for rec in group["member_records"]
            ],
            "pairing_reasons": group.get("pairing_reasons", {}),
        }
        response = ask_ollama(model, payload, timeout)
        canonical_name = choose_canonical_name_from_response(response, group)
        result = (
            {
                "group_id": group["group_id"],
                "canonical_name": canonical_name,
                "response": response,
                "input_members": group["members"],
            }
        )
        results.append(result)
        emit_runtime_event(
            "manuscriptprep-resolver",
            "resolve_group_success",
            group_id=group["group_id"],
            group_index=index,
            total_groups=total_groups,
            canonical_name=canonical_name,
            merge=bool(response.get("merge", False)),
            confidence=response.get("confidence", "review"),
            candidate_names=group["members"],
        )
    return results

def build_resolution_map(llm_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    resolution_entries = []
    variant_to_canonical: Dict[str, Dict[str, Any]] = {}

    for item in llm_results:
        resp = item["response"]
        canonical_name = item["canonical_name"]
        merge = bool(resp.get("merge", False))
        confidence = resp.get("confidence", "review")
        members_to_merge = [m for m in resp.get("members_to_merge", []) if isinstance(m, str)]
        members_to_keep_separate = [m for m in resp.get("members_to_keep_separate", []) if isinstance(m, str)]
        reasons = [r for r in resp.get("reasons", []) if isinstance(r, str)]

        entry = {
            "group_id": item["group_id"],
            "canonical_name": canonical_name,
            "merge": merge,
            "confidence": confidence,
            "members_to_merge": unique_preserve_order(members_to_merge),
            "members_to_keep_separate": unique_preserve_order(members_to_keep_separate),
            "reasons": unique_preserve_order(reasons),
        }
        resolution_entries.append(entry)

        if merge:
            for variant in entry["members_to_merge"]:
                variant_to_canonical[norm_text(variant)] = {
                    "variant": variant,
                    "canonical_name": canonical_name,
                    "confidence": confidence,
                    "reasons": entry["reasons"],
                }

    return {
        "resolutions": resolution_entries,
        "variant_to_canonical": variant_to_canonical,
    }

def apply_resolution_to_book(book_merged: Dict[str, Any], resolution_map: Dict[str, Any]) -> Dict[str, Any]:
    out = json.loads(json.dumps(book_merged))
    vmap = resolution_map.get("variant_to_canonical", {})

    # Resolved character list
    raw_chars = out.get("entities", {}).get("characters", [])
    resolved_characters = []
    for ch in raw_chars:
        if isinstance(ch, str):
            match = vmap.get(norm_text(ch))
            resolved_characters.append(match["canonical_name"] if match else ch)
    out.setdefault("entities", {})["characters_resolved"] = unique_preserve_order(resolved_characters)

    # Annotate dossiers
    for dossier in out.get("dossiers", {}).get("character_dossiers", []):
        if not isinstance(dossier, dict):
            continue
        candidates = dossier.get("surface_variants") or dossier.get("variants") or [dossier.get("name", "")]
        matched = None
        for c in candidates:
            if isinstance(c, str):
                m = vmap.get(norm_text(c))
                if m:
                    matched = m
                    break
        if matched:
            dossier["resolved_canonical_name"] = matched["canonical_name"]
            dossier["resolver_confidence"] = matched["confidence"]
            dossier["resolver_reasons"] = matched["reasons"]
        else:
            dossier["resolved_canonical_name"] = dossier.get("canonical_name") or dossier.get("name")

    out["resolution_map"] = resolution_map
    return out


def resolve_resolver_settings(args: argparse.Namespace, cfg: Optional[ManuscriptPrepConfig]) -> ResolverRuntimeSettings:
    if cfg is None:
        if args.input_dir is None or args.output_dir is None or args.model is None:
            raise ConfigError(
                "Missing required --input-dir, --output-dir, or --model. Provide them explicitly, or use --config with --book-slug."
            )
        return ResolverRuntimeSettings(
            input_dir=args.input_dir.expanduser(),
            output_dir=args.output_dir.expanduser(),
            model=args.model,
            timeout=args.timeout if args.timeout is not None else 180,
            min_variant_count=args.min_variant_count if args.min_variant_count is not None else 2,
            max_group_size=args.max_group_size if args.max_group_size is not None else 8,
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
        input_dir = input_dir or (paths.merged_root / slug)
        output_dir = output_dir or (paths.resolved_root / slug)

    model = args.model or str(cfg.require("models", "resolver"))
    timeout = args.timeout if args.timeout is not None else int(cfg.get("timeouts", "resolver_timeout_seconds", default=180))
    min_variant_count = args.min_variant_count if args.min_variant_count is not None else 2
    max_group_size = args.max_group_size if args.max_group_size is not None else 8

    return ResolverRuntimeSettings(
        input_dir=input_dir,
        output_dir=output_dir,
        model=model,
        timeout=timeout,
        min_variant_count=min_variant_count,
        max_group_size=max_group_size,
        config_path=cfg.path,
    )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Book-level LLM resolver for ManuscriptPrep.")
    parser.add_argument("--config", type=Path, default=None, help="Optional YAML config file")
    parser.add_argument("--book-slug", default=None, help="Book slug used to derive config-based paths")
    parser.add_argument("--input-dir", type=Path, required=False, help="Merged book directory")
    parser.add_argument("--output-dir", type=Path, required=False, help="Output directory for resolved artifacts")
    parser.add_argument("--model", required=False, help="Ollama model name to use for resolution")
    parser.add_argument("--timeout", type=int, default=None, help="Per-group Ollama timeout in seconds")
    parser.add_argument("--min-variant-count", type=int, default=None, help="Minimum group size to send for LLM resolution")
    parser.add_argument("--max-group-size", type=int, default=None, help="Maximum candidate group size")
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    try:
        cfg = load_config(args.config) if args.config is not None else None
        settings = resolve_resolver_settings(args, cfg)
    except (ConfigError, RuntimeError) as exc:
        raise SystemExit(str(exc))
    if not settings.input_dir.is_dir():
        raise SystemExit(f"Input dir does not exist: {settings.input_dir}")

    book_merged = read_json(settings.input_dir / "book_merged.json")
    entities = read_json(settings.input_dir / "entities_merged.json")
    dossiers = read_json(settings.input_dir / "dossiers_merged.json")
    conflict_report = read_json(settings.input_dir / "conflict_report.json")

    pool = build_character_pool(book_merged, entities, dossiers, conflict_report)
    groups = cluster_candidates(
        pool=pool,
        min_variant_count=settings.min_variant_count,
        max_group_size=settings.max_group_size,
    )

    llm_results = resolve_groups_with_llm(groups, settings.model, settings.timeout)
    resolution_map = build_resolution_map(llm_results)
    book_resolved = apply_resolution_to_book(book_merged, resolution_map)
    book_resolved["config_path"] = str(settings.config_path.resolve()) if settings.config_path is not None else None

    resolution_report = {
        "model": settings.model,
        "candidate_group_count": len(groups),
        "resolved_group_count": len(llm_results),
        "merged_group_count": sum(1 for r in resolution_map.get("resolutions", []) if r.get("merge")),
        "variant_mapping_count": len(resolution_map.get("variant_to_canonical", {})),
        "config_path": str(settings.config_path.resolve()) if settings.config_path is not None else None,
    }

    settings.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(settings.output_dir / "resolution_candidates.json", {"groups": groups})
    write_json(settings.output_dir / "resolution_map.json", resolution_map)
    write_json(settings.output_dir / "resolution_report.json", resolution_report)
    write_json(settings.output_dir / "book_resolved.json", book_resolved)

    print(f"Resolved {len(groups)} candidate groups with model {settings.model}")
    print(f"Wrote resolved outputs to {settings.output_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
