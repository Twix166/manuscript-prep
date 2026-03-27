"""Path helpers for ManuscriptPrep."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscriptprep.config import ManuscriptPrepConfig


@dataclass
class PathSet:
    repo_root: Path
    workspace_root: Path
    input_root: Path
    extracted_root: Path
    cleaned_root: Path
    chunks_root: Path
    output_root: Path
    merged_root: Path
    resolved_root: Path
    reports_root: Path
    logs_root: Path


def build_paths(cfg: ManuscriptPrepConfig) -> PathSet:
    p = cfg.require("paths")
    return PathSet(
        repo_root=Path(p["repo_root"]).expanduser(),
        workspace_root=Path(p["workspace_root"]).expanduser(),
        input_root=Path(p["input_root"]).expanduser(),
        extracted_root=Path(p["extracted_root"]).expanduser(),
        cleaned_root=Path(p["cleaned_root"]).expanduser(),
        chunks_root=Path(p["chunks_root"]).expanduser(),
        output_root=Path(p["output_root"]).expanduser(),
        merged_root=Path(p["merged_root"]).expanduser(),
        resolved_root=Path(p["resolved_root"]).expanduser(),
        reports_root=Path(p["reports_root"]).expanduser(),
        logs_root=Path(p["logs_root"]).expanduser(),
    )


def ensure_common_dirs(paths: PathSet) -> None:
    for path in [
        paths.workspace_root,
        paths.input_root,
        paths.extracted_root,
        paths.cleaned_root,
        paths.chunks_root,
        paths.output_root,
        paths.merged_root,
        paths.resolved_root,
        paths.reports_root,
        paths.logs_root,
    ]:
        path.mkdir(parents=True, exist_ok=True)
