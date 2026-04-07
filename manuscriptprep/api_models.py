"""API-facing request and response models for early service extraction.

These dataclasses define the first stable contract between clients and the
pipeline runtime. The initial slice keeps the store in-process and the
execution backend local, but the job and stage model is intentionally
transport-friendly so the same payloads can be used by a TUI or web UI later.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StageDefinition:
    name: str
    kind: str
    description: str
    deterministic: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineDefinition:
    pipeline: str
    stages: List[StageDefinition]


@dataclass
class JobCreateRequest:
    pipeline: str
    book_slug: Optional[str] = None
    title: Optional[str] = None
    manuscript_id: Optional[str] = None
    config_profile_id: Optional[str] = None
    config_path: Optional[str] = None
    input_path: Optional[str] = None
    owner_user_id: Optional[str] = None
    owner_username: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactRef:
    name: str
    path: str
    kind: str
    stage: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StageRun:
    name: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    command: List[str] = field(default_factory=list)
    exit_code: Optional[int] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None


@dataclass
class JobRecord:
    job_id: str
    pipeline: str
    status: str
    created_at: str
    updated_at: str
    book_slug: Optional[str] = None
    title: Optional[str] = None
    manuscript_id: Optional[str] = None
    config_profile_id: Optional[str] = None
    config_path: Optional[str] = None
    input_path: Optional[str] = None
    owner_user_id: Optional[str] = None
    owner_username: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)
    stage_runs: List[StageRun] = field(default_factory=list)
    artifacts: List[ArtifactRef] = field(default_factory=list)


@dataclass
class WorkerHeartbeat:
    worker_id: str
    status: str
    heartbeat_at: str
    last_job_id: Optional[str] = None


@dataclass
class UserRecord:
    user_id: str
    username: str
    role: str
    api_token: str
    created_at: str
    updated_at: str


@dataclass
class ManuscriptRecord:
    manuscript_id: str
    book_slug: str
    title: str
    source_path: str
    file_size_bytes: Optional[int]
    owner_user_id: Optional[str]
    owner_username: Optional[str]
    created_at: str
    updated_at: str


@dataclass
class ManuscriptIngestSummary:
    job_id: str
    pipeline: str
    status: str
    started_at: Optional[str]
    finished_at: Optional[str]
    updated_at: str
    error: Optional[str] = None


@dataclass
class ConfigProfileRecord:
    config_profile_id: str
    name: str
    config_path: str
    version: str
    checksum: str
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def to_dict(obj: Any) -> Dict[str, Any]:
    return asdict(obj)


def to_json(obj: Any) -> str:
    return json.dumps(asdict(obj), indent=2, ensure_ascii=False)
