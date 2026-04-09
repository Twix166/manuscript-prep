#!/usr/bin/env python3
"""Minimal HTTP gateway for the current API-oriented microservices slice.

This service is intentionally small:
- no external framework dependency
- explicit JSON contracts
- pluggable file or PostgreSQL-backed job persistence

The goal is to establish the API surface that a future TUI client or web UI
can target while workers execute long-running jobs out of process.
"""

from __future__ import annotations

import argparse
import mimetypes
import hashlib
import hmac
import io
import json
import os
import secrets
import zipfile
from collections import Counter
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse
import re

from manuscriptprep.api_models import (
    JobCreateRequest,
    ManuscriptIngestSummary,
    UserRecord,
    to_dict,
    utc_now_iso,
)
from manuscriptprep.config import load_config
from manuscriptprep.job_store import BaseJobStore
from manuscriptprep.paths import build_paths
from manuscriptprep.runtime_logging import emit_runtime_event
from manuscriptprep.service_registry import get_pipeline_definition, list_pipelines
from manuscriptprep.store_factory import create_job_store
from manuscriptprep.web_ui import get_web_asset


class GatewayAPI:
    def __init__(
        self,
        store: BaseJobStore | None = None,
        runtime_root: Path | None = None,
        auth_required: bool = False,
        bootstrap_username: str | None = None,
        bootstrap_token: str | None = None,
        bootstrap_role: str = "admin",
        bootstrap_config_profile_name: str | None = None,
        bootstrap_config_profile_path: str | None = None,
        bootstrap_config_profile_version: str = "v1",
    ) -> None:
        self.store = store or create_job_store(backend="file", jobs_root=Path("work/gateway_jobs"))
        self.runtime_root = runtime_root or getattr(self.store, "root", Path("work/gateway_jobs")) / "runtime"
        self.upload_root = self.runtime_root.parent / "uploads"
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.auth_required = auth_required
        self.bootstrap_admin_username = bootstrap_username or "admin"
        if bootstrap_token:
            self.store.upsert_user(username=self.bootstrap_admin_username, role=bootstrap_role, api_token=bootstrap_token)
        if bootstrap_config_profile_name and bootstrap_config_profile_path:
            checksum = hashlib.sha256(str(bootstrap_config_profile_path).encode("utf-8")).hexdigest()
            self.store.upsert_config_profile(
                name=bootstrap_config_profile_name,
                config_path=bootstrap_config_profile_path,
                version=bootstrap_config_profile_version,
                checksum=checksum,
                metadata=self._config_profile_metadata(bootstrap_config_profile_path),
            )

    def _slugify(self, value: str) -> str:
        import re

        text = value.lower()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s\-]+", "_", text)
        text = re.sub(r"_+", "_", text)
        return text.strip("_")

    def _sanitize_filename(self, filename: str) -> str:
        name = Path(filename).name
        stem = self._slugify(Path(name).stem) or "manuscript"
        suffix = Path(name).suffix or ".pdf"
        return f"{stem}{suffix}"

    def _detect_manuscript_format(
        self,
        *,
        filename: str,
        body: bytes,
        content_type: str | None = None,
    ) -> tuple[str | None, str | None]:
        suffix = Path(filename).suffix.lower()
        content_type = (content_type or "").split(";", 1)[0].strip().lower()
        extension_map = {
            ".pdf": "pdf",
            ".docx": "docx",
            ".epub": "epub",
            ".odt": "odt",
            ".mobi": "mobi",
            ".azw": "azw",
            ".azw3": "azw3",
            ".txt": "txt",
        }
        mime_map = {
            "application/pdf": "pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "application/epub+zip": "epub",
            "application/vnd.oasis.opendocument.text": "odt",
            "application/x-mobipocket-ebook": "mobi",
            "application/vnd.amazon.ebook": extension_map.get(suffix, "azw3"),
            "text/plain": "txt",
        }

        if body.startswith(b"%PDF"):
            return "pdf", "Portable Document Format"
        if b"BOOKMOBI" in body[:256]:
            return extension_map.get(suffix, "mobi"), "Kindle / Mobipocket"
        if body.startswith(b"PK"):
            try:
                with zipfile.ZipFile(io.BytesIO(body)) as archive:
                    names = set(archive.namelist())
                    if "word/document.xml" in names:
                        return "docx", "Microsoft Word Document"
                    if "mimetype" in names:
                        mimetype_value = archive.read("mimetype").decode("utf-8", errors="ignore").strip()
                        if mimetype_value == "application/epub+zip":
                            return "epub", "EPUB Ebook"
                        if mimetype_value == "application/vnd.oasis.opendocument.text":
                            return "odt", "OpenDocument Text"
            except zipfile.BadZipFile:
                pass

        detected = extension_map.get(suffix) or mime_map.get(content_type)
        label_map = {
            "pdf": "Portable Document Format",
            "docx": "Microsoft Word Document",
            "epub": "EPUB Ebook",
            "odt": "OpenDocument Text",
            "mobi": "Kindle / Mobipocket",
            "azw": "Kindle / AZW",
            "azw3": "Kindle / AZW3",
            "txt": "Plain Text",
        }
        return detected, label_map.get(detected)

    def _config_profile_metadata(self, config_path: str) -> Dict[str, Any]:
        try:
            cfg = load_config(config_path)
            paths = build_paths(cfg)
        except Exception:
            return {}
        return {
            "project": cfg.data.get("project", {}),
            "models": cfg.data.get("models", {}),
            "chunking": cfg.data.get("chunking", {}),
            "timeouts": cfg.data.get("timeouts", {}),
            "ollama": cfg.data.get("ollama", {}),
            "reporting": cfg.data.get("reporting", {}),
            "paths": {
                "workspace_root": str(paths.workspace_root),
                "chunks_root": str(paths.chunks_root),
                "output_root": str(paths.output_root),
                "merged_root": str(paths.merged_root),
                "resolved_root": str(paths.resolved_root),
                "reports_root": str(paths.reports_root),
            },
        }

    def authenticate(self, token: str | None) -> Optional[UserRecord]:
        if not token:
            return None
        return self.store.get_user_by_token(token)

    def _bootstrap_admin_user(self) -> Optional[UserRecord]:
        return self.store.get_user_by_username(self.bootstrap_admin_username)

    def auth_setup_state(self) -> Tuple[int, Dict[str, Any]]:
        admin = self._bootstrap_admin_user()
        needs_setup = admin is None or not admin.password_hash
        return HTTPStatus.OK, {
            "needs_admin_setup": needs_setup,
            "admin_username": self.bootstrap_admin_username,
        }

    def _serialize_user(self, user: UserRecord) -> Dict[str, Any]:
        return {
            "user_id": user.user_id,
            "username": user.username,
            "role": user.role,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }

    def _hash_password(self, password: str, *, iterations: int = 390_000) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
        return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"

    def _verify_password(self, password: str, password_hash: str | None) -> bool:
        if not password_hash:
            return False
        try:
            algorithm, iteration_text, salt_hex, digest_hex = password_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            iterations = int(iteration_text)
            expected = bytes.fromhex(digest_hex)
            candidate = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                iterations,
            )
            return hmac.compare_digest(candidate, expected)
        except (ValueError, TypeError):
            return False

    def register_user(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        admin = self._bootstrap_admin_user()
        if admin is None or not admin.password_hash:
            return HTTPStatus.FORBIDDEN, {"error": "Complete admin setup before registering users"}
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        if len(username) < 3:
            return HTTPStatus.BAD_REQUEST, {"error": "username must be at least 3 characters"}
        if len(password) < 8:
            return HTTPStatus.BAD_REQUEST, {"error": "password must be at least 8 characters"}
        existing = self.store.get_user_by_username(username)
        if existing is not None:
            return HTTPStatus.CONFLICT, {"error": "username is already registered"}
        api_token = secrets.token_urlsafe(32)
        user = self.store.upsert_user(
            username=username,
            role="user",
            api_token=api_token,
            password_hash=self._hash_password(password),
        )
        return HTTPStatus.CREATED, {"user": self._serialize_user(user), "api_token": user.api_token}

    def bootstrap_admin_password(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        username = str(payload.get("username", self.bootstrap_admin_username)).strip() or self.bootstrap_admin_username
        password = str(payload.get("password", ""))
        if username != self.bootstrap_admin_username:
            return HTTPStatus.BAD_REQUEST, {"error": "Bootstrap admin username cannot be changed"}
        if len(password) < 8:
            return HTTPStatus.BAD_REQUEST, {"error": "password must be at least 8 characters"}
        user = self._bootstrap_admin_user()
        if user is not None and user.password_hash:
            return HTTPStatus.CONFLICT, {"error": "Admin setup has already been completed"}
        if user is None:
            api_token = secrets.token_urlsafe(32)
            user = self.store.upsert_user(
                username=self.bootstrap_admin_username,
                role="admin",
                api_token=api_token,
                password_hash=self._hash_password(password),
            )
        else:
            user = self.store.upsert_user(
                username=user.username,
                role=user.role,
                api_token=user.api_token,
                password_hash=self._hash_password(password),
            )
        return HTTPStatus.CREATED, {"user": self._serialize_user(user), "api_token": user.api_token}

    def login_user(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        user = self.store.get_user_by_username(username)
        if user is None or not self._verify_password(password, user.password_hash):
            return HTTPStatus.UNAUTHORIZED, {"error": "Invalid username or password"}
        return HTTPStatus.OK, {"user": self._serialize_user(user), "api_token": user.api_token}

    def current_user(self, actor: Optional[UserRecord]) -> Tuple[int, Dict[str, Any]]:
        if actor is None:
            return HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"}
        return HTTPStatus.OK, {"user": self._serialize_user(actor)}

    def _require_actor(self, actor: Optional[UserRecord]) -> Tuple[bool, Tuple[int, Dict[str, Any]] | None]:
        if not self.auth_required:
            return True, None
        if actor is None:
            return False, (HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
        return True, None

    def _can_access_job(self, actor: Optional[UserRecord], job_owner_user_id: Optional[str]) -> bool:
        if not self.auth_required:
            return True
        if actor is None:
            return False
        if actor.role == "admin":
            return True
        return actor.user_id == job_owner_user_id

    def _can_access_manuscript(self, actor: Optional[UserRecord], owner_user_id: Optional[str]) -> bool:
        return self._can_access_job(actor, owner_user_id)

    def health(self) -> Tuple[int, Dict[str, Any]]:
        return HTTPStatus.OK, {"status": "ok", "service": "gateway-api", "timestamp": utc_now_iso()}

    def ready(self) -> Tuple[int, Dict[str, Any]]:
        ready = self.store.is_ready()
        payload = {
            "status": "ready" if ready else "not_ready",
            "service": "gateway-api",
            "timestamp": utc_now_iso(),
        }
        return (HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE), payload

    def system_status(self, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        if actor is not None and actor.role != "admin":
            return HTTPStatus.FORBIDDEN, {"error": "Admin access required"}
        workers = [to_dict(item) for item in self.store.list_worker_heartbeats()]
        return HTTPStatus.OK, {
            "service": "gateway-api",
            "timestamp": utc_now_iso(),
            "store_backend": self.store.__class__.__name__,
            "ready": self.store.is_ready(),
            "queue": self.store.queue_summary(),
            "workers": workers,
        }

    def list_pipelines(self, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        return HTTPStatus.OK, {"pipelines": [to_dict(item) for item in list_pipelines()]}

    def list_manuscripts(self, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        manuscripts = self.store.list_manuscripts()
        if self.auth_required and actor is not None and actor.role != "admin":
            manuscripts = [item for item in manuscripts if item.owner_user_id == actor.user_id]
        return HTTPStatus.OK, {"manuscripts": [self._serialize_manuscript(item) for item in manuscripts]}

    def _latest_ingest_summary(self, manuscript_id: str) -> Optional[ManuscriptIngestSummary]:
        jobs = sorted(self.store.list_jobs(), key=lambda item: item.updated_at, reverse=True)
        for job in jobs:
            if job.manuscript_id != manuscript_id:
                continue
            for stage in job.stage_runs:
                if stage.name != "ingest":
                    continue
                return ManuscriptIngestSummary(
                    job_id=job.job_id,
                    pipeline=job.pipeline,
                    status=stage.status,
                    started_at=stage.started_at,
                    finished_at=stage.finished_at,
                    updated_at=job.updated_at,
                    error=stage.error,
                )
        return None

    def _serialize_manuscript(self, manuscript) -> Dict[str, Any]:
        payload = to_dict(manuscript)
        latest_ingest = self._latest_ingest_summary(manuscript.manuscript_id)
        payload["latest_ingest"] = to_dict(latest_ingest) if latest_ingest is not None else None
        return payload

    def create_manuscript(self, payload: Dict[str, Any], actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        for field in ("title", "source_path"):
            if not payload.get(field):
                return HTTPStatus.BAD_REQUEST, {"error": f"Missing required field: {field}"}
        manuscript = self.store.upsert_manuscript(
            book_slug=str(payload.get("book_slug") or self._slugify(str(payload["title"])) or "manuscript"),
            title=str(payload["title"]),
            source_path=str(payload["source_path"]),
            file_size_bytes=(int(payload["file_size_bytes"]) if payload.get("file_size_bytes") is not None else None),
            owner_user_id=actor.user_id if actor else payload.get("owner_user_id"),
            owner_username=actor.username if actor else payload.get("owner_username"),
        )
        return HTTPStatus.CREATED, self._serialize_manuscript(manuscript)

    def update_manuscript(self, manuscript_id: str, payload: Dict[str, Any], actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        manuscript = self.store.get_manuscript(manuscript_id)
        if manuscript is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown manuscript: {manuscript_id}"}
        if not self._can_access_manuscript(actor, manuscript.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this manuscript"}
        next_title = payload.get("title")
        next_slug = payload.get("book_slug")
        if next_title is not None:
            next_title = str(next_title).strip()
            if not next_title:
                return HTTPStatus.BAD_REQUEST, {"error": "title cannot be blank"}
        if next_slug is not None:
            next_slug = self._slugify(str(next_slug))
            if not next_slug:
                return HTTPStatus.BAD_REQUEST, {"error": "book_slug cannot be blank"}
        updated = self.store.update_manuscript(manuscript_id, title=next_title, book_slug=next_slug)
        if updated is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown manuscript: {manuscript_id}"}
        return HTTPStatus.OK, self._serialize_manuscript(updated)

    def delete_manuscript(self, manuscript_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        manuscript = self.store.get_manuscript(manuscript_id)
        if manuscript is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown manuscript: {manuscript_id}"}
        if not self._can_access_manuscript(actor, manuscript.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this manuscript"}
        if not self.store.delete_manuscript(manuscript_id):
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown manuscript: {manuscript_id}"}
        return HTTPStatus.OK, {"deleted": True, "manuscript_id": manuscript_id}

    def get_manuscript_ingest_results(self, manuscript_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        manuscript = self.store.get_manuscript(manuscript_id)
        if manuscript is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown manuscript: {manuscript_id}"}
        if not self._can_access_manuscript(actor, manuscript.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this manuscript"}
        latest_ingest = self._latest_ingest_summary(manuscript_id)
        if latest_ingest is None:
            return HTTPStatus.NOT_FOUND, {"error": "No ingest results available for this manuscript yet"}
        job = self.store.get_job(latest_ingest.job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {latest_ingest.job_id}"}

        artifacts = {}
        for artifact_name in ("ingest_manifest", "raw_text", "clean_text", "chunk_manifest"):
            status, payload = self.get_job_artifact(latest_ingest.job_id, artifact_name, actor=actor)
            if status != HTTPStatus.OK:
                return HTTPStatus.NOT_FOUND, {"error": f"Missing ingest artifact: {artifact_name}"}
            artifact_meta = payload.get("artifact", {})
            artifact_path = Path(str(artifact_meta.get("path", "")))
            artifact_kind = str(artifact_meta.get("kind", ""))
            if payload.get("exists") and artifact_kind in {"text", "json", "jsonl"} and artifact_path.is_file():
                content = artifact_path.read_text(encoding="utf-8")
                payload["content"] = content if artifact_kind == "text" else json.loads(content)
            artifacts[artifact_name] = payload
        return HTTPStatus.OK, {
            "manuscript": self._serialize_manuscript(manuscript),
            "job": to_dict(job),
            **artifacts,
        }

    def upload_manuscript(
        self,
        *,
        filename: str,
        body: bytes,
        content_type: str | None = None,
        actor: Optional[UserRecord] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        if not filename:
            return HTTPStatus.BAD_REQUEST, {"error": "Missing required upload filename"}
        detected_format, detected_label = self._detect_manuscript_format(
            filename=filename,
            body=body,
            content_type=content_type,
        )
        if detected_format is None:
            return HTTPStatus.BAD_REQUEST, {
                "error": "Unsupported manuscript format. Use PDF, DOCX, EPUB, ODT, MOBI, AZW, AZW3, or TXT.",
            }
        safe_name = self._sanitize_filename(filename)
        owner_dir = self.upload_root / (actor.user_id if actor else "anonymous")
        owner_dir.mkdir(parents=True, exist_ok=True)
        destination = owner_dir / safe_name
        destination.write_bytes(body)
        return HTTPStatus.CREATED, {
            "filename": safe_name,
            "path": str(destination),
            "size_bytes": len(body),
            "book_slug_guess": self._slugify(Path(safe_name).stem),
            "detected_format": detected_format,
            "detected_label": detected_label,
            "content_type": content_type,
        }

    def list_config_profiles(self, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        return HTTPStatus.OK, {"config_profiles": [to_dict(item) for item in self.store.list_config_profiles()]}

    def create_config_profile(self, payload: Dict[str, Any], actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        if actor is not None and actor.role != "admin":
            return HTTPStatus.FORBIDDEN, {"error": "Admin access required"}
        for field in ("name", "config_path", "version"):
            if not payload.get(field):
                return HTTPStatus.BAD_REQUEST, {"error": f"Missing required field: {field}"}
        checksum = payload.get("checksum")
        if not checksum:
            checksum = hashlib.sha256(str(payload["config_path"]).encode("utf-8")).hexdigest()
        metadata = self._config_profile_metadata(str(payload["config_path"]))
        profile = self.store.upsert_config_profile(
            name=str(payload["name"]),
            config_path=str(payload["config_path"]),
            version=str(payload["version"]),
            checksum=str(checksum),
            metadata=metadata,
        )
        return HTTPStatus.CREATED, to_dict(profile)

    def list_jobs(
        self,
        actor: Optional[UserRecord] = None,
        manuscript_id: Optional[str] = None,
        pipeline: Optional[str] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        jobs = self.store.list_jobs()
        if self.auth_required and actor is not None and actor.role != "admin":
            jobs = [job for job in jobs if job.owner_user_id == actor.user_id]
        if manuscript_id:
            jobs = [job for job in jobs if job.manuscript_id == manuscript_id]
        if pipeline:
            jobs = [job for job in jobs if job.pipeline == pipeline]
        return HTTPStatus.OK, {"jobs": [to_dict(item) for item in jobs]}

    def _resolve_orchestrate_progress_paths(self, job) -> Tuple[Optional[Path], Optional[Path]]:
        input_dir = job.options.get("input_dir")
        output_dir = job.options.get("output_dir")
        log_path: Optional[Path] = None
        if (not input_dir or not output_dir) and job.config_path and job.book_slug:
            cfg = load_config(job.config_path)
            paths = build_paths(cfg)
            input_dir = input_dir or str(paths.chunks_root / str(job.book_slug))
            output_dir = output_dir or str(paths.output_root / str(job.book_slug))
            logs_root = cfg.data.get("paths", {}).get("logs_root")
            if logs_root:
                log_path = Path(str(logs_root)).expanduser() / "orchestrator.log.jsonl"
        if not input_dir or not output_dir:
            return None, None
        return Path(str(input_dir)), (log_path or (Path(str(output_dir)) / "orchestrator.log.jsonl"))

    def _pass_order(self) -> list[str]:
        return ["structure", "dialogue", "entities", "dossiers"]

    def _chunk_index_from_name(self, chunk_name: Optional[str]) -> Optional[int]:
        if not chunk_name:
            return None
        match = re.search(r"(\d+)$", str(chunk_name))
        if not match:
            return None
        return int(match.group(1)) + 1

    def _resolve_orchestrate_output_dir(self, job) -> Optional[Path]:
        output_dir = job.options.get("output_dir")
        if not output_dir and job.config_path and job.book_slug:
            cfg = load_config(job.config_path)
            paths = build_paths(cfg)
            output_dir = str(paths.output_root / str(job.book_slug))
        if not output_dir:
            return None
        return Path(str(output_dir))

    def _load_json_file(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _build_chunk_analysis_summary(self, chunk_dir: Path) -> Dict[str, Any]:
        structure = self._load_json_file(chunk_dir / "structure.json")
        dialogue = self._load_json_file(chunk_dir / "dialogue.json")
        entities = self._load_json_file(chunk_dir / "entities.json")
        dossiers = self._load_json_file(chunk_dir / "dossiers.json")
        timing = self._load_json_file(chunk_dir / "timing.json")

        passes_completed = [
            pass_name
            for pass_name, payload in {
                "structure": structure,
                "dialogue": dialogue,
                "entities": entities,
                "dossiers": dossiers,
            }.items()
            if payload is not None
        ]

        return {
            "chunk_id": chunk_dir.name,
            "passes_completed": passes_completed,
            "structure": {
                "chapters": (structure or {}).get("chapters", []),
                "parts": (structure or {}).get("parts", []),
                "scene_breaks": (structure or {}).get("scene_breaks", []),
                "status": (structure or {}).get("status"),
            },
            "dialogue": {
                "pov": (dialogue or {}).get("pov"),
                "dialogue": (dialogue or {}).get("dialogue"),
                "internal_thought": (dialogue or {}).get("internal_thought"),
                "explicitly_attributed_speakers": (dialogue or {}).get("explicitly_attributed_speakers", []),
                "unattributed_dialogue_present": (dialogue or {}).get("unattributed_dialogue_present"),
            },
            "entities": {
                "characters": (entities or {}).get("characters", []),
                "places": (entities or {}).get("places", []),
                "objects": (entities or {}).get("objects", []),
                "identity_notes": (entities or {}).get("identity_notes", []),
            },
            "dossiers": {
                "character_dossiers": (dossiers or {}).get("character_dossiers", []),
            },
            "timing": timing or {},
        }

    def _chunk_has_analysis_output(self, chunk_summary: Dict[str, Any]) -> bool:
        return bool(
            chunk_summary["passes_completed"]
            or chunk_summary["timing"]
            or chunk_summary["structure"]["chapters"]
            or chunk_summary["structure"]["parts"]
            or chunk_summary["structure"]["scene_breaks"]
            or chunk_summary["dialogue"]["pov"]
            or chunk_summary["dialogue"]["dialogue"] is not None
            or chunk_summary["entities"]["characters"]
            or chunk_summary["entities"]["places"]
            or chunk_summary["entities"]["objects"]
            or chunk_summary["entities"]["identity_notes"]
            or chunk_summary["dossiers"]["character_dossiers"]
        )

    def _build_orchestrate_progress(self, job) -> Dict[str, Any]:
        input_dir, log_path = self._resolve_orchestrate_progress_paths(job)
        total_chunks = 0
        if input_dir and input_dir.exists():
            total_chunks = len([item for item in input_dir.glob("*.txt") if item.is_file()])

        progress: Dict[str, Any] = {
            "job_id": job.job_id,
            "pipeline": job.pipeline,
            "available": bool(log_path and log_path.exists()),
            "chunks_total": total_chunks,
            "chunks_completed": 0,
            "chunks_failed": 0,
            "current_chunk": None,
            "current_chunk_index": None,
            "chunk_percent": 0.0,
            "current_pass": None,
            "current_pass_index": None,
            "pass_percent": 0.0,
            "current_step": None,
            "current_model": None,
            "current_attempt": None,
            "current_idle_timeout_s": None,
            "idle_backoffs": 0,
            "reported_tps": None,
            "estimated_tps": None,
            "last_event_type": None,
            "last_event_at": None,
            "recent_events": [],
        }
        if not log_path or not log_path.exists():
            return progress

        lower_bound = None
        try:
            lower_bound = datetime.fromisoformat(job.created_at)
        except ValueError:
            lower_bound = None
        orchestrate_stage = next((stage for stage in job.stage_runs if stage.name == "orchestrate"), None)
        if orchestrate_stage and orchestrate_stage.started_at:
            try:
                stage_started_at = datetime.fromisoformat(orchestrate_stage.started_at)
            except ValueError:
                stage_started_at = None
            if stage_started_at is not None and (lower_bound is None or stage_started_at > lower_bound):
                lower_bound = stage_started_at

        pass_order = self._pass_order()
        chunk_starts: list[str] = []
        counts = Counter()
        recent_events: list[Dict[str, Any]] = []
        latest_for_chunk: Dict[str, Any] = {}

        with log_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if lower_bound is not None and event.get("timestamp"):
                    try:
                        event_ts = datetime.fromisoformat(str(event["timestamp"]))
                    except ValueError:
                        event_ts = None
                    if event_ts is not None and event_ts < lower_bound:
                        continue
                event_type = event.get("event_type")
                chunk = event.get("chunk")
                if event_type == "chunk_start" and chunk:
                    chunk_starts.append(chunk)
                if event_type in {"chunk_success", "chunk_failure"}:
                    counts[event_type] += 1
                if chunk:
                    latest_for_chunk[chunk] = event
                recent_events.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "event_type": event_type,
                        "chunk": chunk,
                        "pass": event.get("pass"),
                        "step": event.get("step"),
                        "message": event.get("message"),
                    }
                )
                if len(recent_events) > 8:
                    recent_events = recent_events[-8:]

                progress["last_event_type"] = event_type
                progress["last_event_at"] = event.get("timestamp")
                if event.get("step"):
                    progress["current_step"] = event.get("step")
                if event.get("model"):
                    progress["current_model"] = event.get("model")
                if event.get("attempt") is not None:
                    progress["current_attempt"] = event.get("attempt")
                if event.get("idle_timeout_s") is not None:
                    progress["current_idle_timeout_s"] = event.get("idle_timeout_s")
                if event.get("idle_timeout_failures_for_pass") is not None:
                    progress["idle_backoffs"] = event.get("idle_timeout_failures_for_pass")
                if event.get("reported_tps") is not None:
                    progress["reported_tps"] = event.get("reported_tps")
                if event.get("estimated_tps") is not None:
                    progress["estimated_tps"] = event.get("estimated_tps")
                if event.get("pass") in pass_order:
                    progress["current_pass"] = event.get("pass")

        progress["chunks_completed"] = counts["chunk_success"]
        progress["chunks_failed"] = counts["chunk_failure"]
        progress["recent_events"] = recent_events

        current_chunk = None
        for chunk_name in reversed(chunk_starts):
            last_for_chunk = latest_for_chunk.get(chunk_name, {})
            if last_for_chunk.get("event_type") not in {"chunk_success", "chunk_failure"}:
                current_chunk = chunk_name
                break
        if current_chunk is None and chunk_starts:
            current_chunk = chunk_starts[-1]

        progress["current_chunk"] = current_chunk
        if current_chunk:
            progress["current_chunk_index"] = self._chunk_index_from_name(current_chunk) or (progress["chunks_completed"] + 1)
        elif progress["chunks_completed"] and total_chunks and progress["chunks_completed"] >= total_chunks:
            progress["current_chunk_index"] = total_chunks

        if total_chunks > 0:
            if current_chunk and progress["current_chunk_index"]:
                progress["chunk_percent"] = round((progress["current_chunk_index"] - 1) / total_chunks * 100, 1)
            else:
                progress["chunk_percent"] = round(progress["chunks_completed"] / total_chunks * 100, 1)

        if progress["current_pass"] in pass_order:
            progress["current_pass_index"] = pass_order.index(progress["current_pass"]) + 1
            progress["pass_percent"] = round((progress["current_pass_index"] - 1) / len(pass_order) * 100, 1)

        return progress

    def get_job_progress(self, job_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}

        if job.pipeline == "orchestrate":
            return HTTPStatus.OK, self._build_orchestrate_progress(job)

        return HTTPStatus.OK, {
            "job_id": job.job_id,
            "pipeline": job.pipeline,
            "available": False,
            "message": "Live chunk progress is currently available for categorisation and analysis jobs only.",
        }

    def get_job_analysis_details(self, job_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}
        if job.pipeline != "orchestrate":
            return HTTPStatus.BAD_REQUEST, {"error": "Analysis details are available for categorisation and analysis jobs only"}

        output_dir = self._resolve_orchestrate_output_dir(job)
        progress = self._build_orchestrate_progress(job)
        if output_dir is None or not output_dir.exists():
            return HTTPStatus.OK, {
                "job_id": job.job_id,
                "available": False,
                "message": "No analysis chunk outputs are available for this job yet.",
                "progress": progress,
                "chunks": [],
            }

        chunk_dirs = sorted(
            [item for item in output_dir.iterdir() if item.is_dir() and item.name.startswith("chunk_")],
            key=lambda item: item.name,
        )
        chunks = []
        for chunk_dir in chunk_dirs:
            summary = self._build_chunk_analysis_summary(chunk_dir)
            if self._chunk_has_analysis_output(summary):
                chunks.append(summary)
        return HTTPStatus.OK, {
            "job_id": job.job_id,
            "available": bool(chunks),
            "progress": progress,
            "chunks_total": progress.get("chunks_total") or len(chunk_dirs),
            "chunks_with_outputs": len(chunks),
            "chunks": chunks,
        }

    def get_job(self, job_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}
        return HTTPStatus.OK, to_dict(job)

    def get_job_artifact(self, job_id: str, artifact_name: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}

        artifact = next((item for item in job.artifacts if item.name == artifact_name), None)
        if artifact is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown artifact on job {job_id}: {artifact_name}"}

        path = Path(artifact.path)
        exists = path.exists()
        payload: Dict[str, Any] = {
            "job_id": job_id,
            "artifact": to_dict(artifact),
            "exists": exists,
        }
        if not exists:
            return HTTPStatus.OK, payload

        payload["size_bytes"] = path.stat().st_size
        if artifact.kind in {"text", "json", "jsonl"}:
            content = path.read_text(encoding="utf-8")
            payload["preview"] = content[:4000]
            if artifact.kind == "json":
                try:
                    payload["content"] = json.loads(content)
                except json.JSONDecodeError:
                    payload["content"] = None
        return HTTPStatus.OK, payload

    def download_job_artifact(self, job_id: str, artifact_name: str, actor: Optional[UserRecord] = None) -> Tuple[int, Path | Dict[str, Any], str]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error[0], error[1], "application/json; charset=utf-8"
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}, "application/json; charset=utf-8"
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}, "application/json; charset=utf-8"
        artifact = next((item for item in job.artifacts if item.name == artifact_name), None)
        if artifact is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown artifact on job {job_id}: {artifact_name}"}, "application/json; charset=utf-8"
        path = Path(artifact.path)
        if not path.exists() or not path.is_file():
            return HTTPStatus.NOT_FOUND, {"error": f"Artifact is not available for download: {artifact_name}"}, "application/json; charset=utf-8"
        content_type, _ = mimetypes.guess_type(path.name)
        if artifact.kind == "json":
            content_type = "application/json; charset=utf-8"
        elif artifact.kind == "jsonl":
            content_type = "application/x-ndjson; charset=utf-8"
        elif artifact.kind == "text":
            content_type = "text/plain; charset=utf-8"
        elif content_type is None:
            content_type = "application/octet-stream"
        return HTTPStatus.OK, path, content_type

    def list_job_artifact_index(self, job_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}
        artifacts = self.store.list_job_artifacts(job_id)
        return HTTPStatus.OK, {"job_id": job_id, "artifacts": [to_dict(item) for item in artifacts]}

    def create_job(self, payload: Dict[str, Any], actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        try:
            manuscript = None
            if payload.get("manuscript_id"):
                manuscript = self.store.get_manuscript(str(payload["manuscript_id"]))
                if manuscript is None:
                    return HTTPStatus.BAD_REQUEST, {"error": f"Unknown manuscript: {payload['manuscript_id']}"}
                if not self._can_access_manuscript(actor, manuscript.owner_user_id):
                    return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this manuscript"}
            config_profile = None
            if payload.get("config_profile_id"):
                config_profile = self.store.get_config_profile(str(payload["config_profile_id"]))
                if config_profile is None:
                    return HTTPStatus.BAD_REQUEST, {"error": f"Unknown config profile: {payload['config_profile_id']}"}

            request = JobCreateRequest(
                pipeline=str(payload["pipeline"]),
                book_slug=(manuscript.book_slug if manuscript else payload.get("book_slug")),
                title=(manuscript.title if manuscript else payload.get("title")),
                manuscript_id=(manuscript.manuscript_id if manuscript else payload.get("manuscript_id")),
                config_profile_id=(config_profile.config_profile_id if config_profile else payload.get("config_profile_id")),
                config_path=(config_profile.config_path if config_profile else payload.get("config_path")),
                input_path=(manuscript.source_path if manuscript else payload.get("input_path")),
                owner_user_id=(actor.user_id if actor else payload.get("owner_user_id")),
                owner_username=(actor.username if actor else payload.get("owner_username")),
                options=payload.get("options", {}) or {},
            )
        except KeyError as exc:
            return HTTPStatus.BAD_REQUEST, {"error": f"Missing required field: {exc.args[0]}"}
        except (TypeError, ValueError) as exc:
            return HTTPStatus.BAD_REQUEST, {"error": str(exc)}

        if get_pipeline_definition(request.pipeline) is None:
            return HTTPStatus.BAD_REQUEST, {"error": f"Unknown pipeline: {request.pipeline}"}

        job = self.store.create_job(request)
        return HTTPStatus.CREATED, to_dict(job)

    def run_job(self, job_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}
        if job.status == "running":
            return HTTPStatus.ACCEPTED, to_dict(job)
        if job.status == "queued":
            return HTTPStatus.ACCEPTED, to_dict(job)
        if job.status == "paused":
            job.status = "queued"
            job.updated_at = utc_now_iso()
            for stage in job.stage_runs:
                if stage.status != "succeeded":
                    stage.status = "pending"
                    stage.finished_at = None
                    stage.error = None
            job.options = {
                key: value
                for key, value in job.options.items()
                if key not in {"_pause_requested_at", "_cancel_requested_at", "_cancel_reason", "_control_target_status", "_worker_id", "_claimed_at"}
            }
            job = self.store.update_job(job)
            return HTTPStatus.ACCEPTED, to_dict(job)
        if job.status in {"succeeded", "failed", "cancelled"}:
            job.status = "queued"
            job.updated_at = utc_now_iso()
            for stage in job.stage_runs:
                stage.status = "pending"
                stage.started_at = None
                stage.finished_at = None
                stage.error = None
                stage.command = []
                stage.exit_code = None
                stage.stdout_path = None
                stage.stderr_path = None
            job.artifacts = []
            job = self.store.update_job(job)
            return HTTPStatus.ACCEPTED, to_dict(job)
        return HTTPStatus.ACCEPTED, to_dict(job)

    def cancel_job(self, job_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}
        updated = self.store.cancel_job(job_id)
        if updated is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        return HTTPStatus.ACCEPTED, to_dict(updated)

    def pause_job(self, job_id: str, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        if not self._can_access_job(actor, job.owner_user_id):
            return HTTPStatus.FORBIDDEN, {"error": "Not authorized for this job"}
        updated = self.store.pause_job(job_id)
        if updated is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        return HTTPStatus.ACCEPTED, to_dict(updated)


class GatewayHandler(BaseHTTPRequestHandler):
    app: GatewayAPI

    def _current_actor(self) -> Optional[UserRecord]:
        auth_header = self.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
        if not token:
            token = self.headers.get("X-API-Token")
        return self.app.authenticate(token)

    def _write_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_file(self, status: int, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _read_raw_body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(content_length) if content_length else b""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in {"/", "/ui", "/ui/"} or path.startswith("/ui/"):
            try:
                content_type, body = get_web_asset(path.lstrip("/") or "index.html")
            except FileNotFoundError:
                self._write_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})
                return
            self._write_bytes(HTTPStatus.OK, body, content_type)
            return

        if path == "/health":
            status, payload = self.app.health()
            self._write_json(status, payload)
            return

        if path == "/ready":
            status, payload = self.app.ready()
            self._write_json(status, payload)
            return

        if path == "/v1/system/status":
            status, payload = self.app.system_status(actor=self._current_actor())
            self._write_json(status, payload)
            return

        if path == "/v1/auth/me":
            status, payload = self.app.current_user(actor=self._current_actor())
            self._write_json(status, payload)
            return

        if path == "/v1/auth/setup-state":
            status, payload = self.app.auth_setup_state()
            self._write_json(status, payload)
            return

        if path == "/v1/pipelines":
            status, payload = self.app.list_pipelines(actor=self._current_actor())
            self._write_json(status, payload)
            return

        if path == "/v1/manuscripts":
            status, payload = self.app.list_manuscripts(actor=self._current_actor())
            self._write_json(status, payload)
            return

        if path.startswith("/v1/manuscripts/") and path.endswith("/ingest-results"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, manuscript_id, _ = parts
                status, payload = self.app.get_manuscript_ingest_results(manuscript_id, actor=self._current_actor())
                self._write_json(status, payload)
                return

        if path == "/v1/config-profiles":
            status, payload = self.app.list_config_profiles(actor=self._current_actor())
            self._write_json(status, payload)
            return

        if path == "/v1/jobs":
            status, payload = self.app.list_jobs(
                actor=self._current_actor(),
                manuscript_id=(query.get("manuscript_id") or [None])[0],
                pipeline=(query.get("pipeline") or [None])[0],
            )
            self._write_json(status, payload)
            return

        if path.startswith("/v1/jobs/") and "/artifacts/" in path:
            parts = path.strip("/").split("/")
            if len(parts) == 6 and parts[-1] == "download":
                _, _, job_id, _, artifact_name, _ = parts
                status, payload, content_type = self.app.download_job_artifact(job_id, artifact_name, actor=self._current_actor())
                if isinstance(payload, Path):
                    self._write_file(status, payload, content_type)
                else:
                    self._write_json(status, payload)
                return
            if len(parts) == 5:
                _, _, job_id, _, artifact_name = parts
                status, payload = self.app.get_job_artifact(job_id, artifact_name, actor=self._current_actor())
                self._write_json(status, payload)
                return

        if path.startswith("/v1/jobs/") and path.endswith("/artifacts"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, job_id, _ = parts
                status, payload = self.app.list_job_artifact_index(job_id, actor=self._current_actor())
                self._write_json(status, payload)
                return

        if path.startswith("/v1/jobs/") and path.endswith("/progress"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, job_id, _ = parts
                status, payload = self.app.get_job_progress(job_id, actor=self._current_actor())
                self._write_json(status, payload)
                return

        if path.startswith("/v1/jobs/") and path.endswith("/analysis-details"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, job_id, _ = parts
                status, payload = self.app.get_job_analysis_details(job_id, actor=self._current_actor())
                self._write_json(status, payload)
                return

        if path.startswith("/v1/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            status, payload = self.app.get_job(job_id, actor=self._current_actor())
            self._write_json(status, payload)
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/v1/uploads/manuscripts":
            status, response = self.app.upload_manuscript(
                filename=self.headers.get("X-Filename", ""),
                body=self._read_raw_body(),
                content_type=self.headers.get("Content-Type", ""),
                actor=self._current_actor(),
            )
            self._write_json(status, response)
            return

        if path == "/v1/auth/register":
            try:
                payload = self._read_json_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            status, response = self.app.register_user(payload)
            self._write_json(status, response)
            return

        if path == "/v1/auth/bootstrap-admin":
            try:
                payload = self._read_json_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            status, response = self.app.bootstrap_admin_password(payload)
            self._write_json(status, response)
            return

        if path == "/v1/auth/login":
            try:
                payload = self._read_json_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            status, response = self.app.login_user(payload)
            self._write_json(status, response)
            return

        if path == "/v1/jobs":
            try:
                payload = self._read_json_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            status, response = self.app.create_job(payload, actor=self._current_actor())
            self._write_json(status, response)
            return

        if path == "/v1/manuscripts":
            try:
                payload = self._read_json_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            status, response = self.app.create_manuscript(payload, actor=self._current_actor())
            self._write_json(status, response)
            return

        if path == "/v1/config-profiles":
            try:
                payload = self._read_json_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            status, response = self.app.create_config_profile(payload, actor=self._current_actor())
            self._write_json(status, response)
            return

        if path.startswith("/v1/jobs/") and path.endswith("/run"):
            job_id = path.split("/")[-2]
            status, response = self.app.run_job(job_id, actor=self._current_actor())
            self._write_json(status, response)
            return

        if path.startswith("/v1/jobs/") and path.endswith("/cancel"):
            job_id = path.split("/")[-2]
            status, response = self.app.cancel_job(job_id, actor=self._current_actor())
            self._write_json(status, response)
            return

        if path.startswith("/v1/jobs/") and path.endswith("/pause"):
            job_id = path.split("/")[-2]
            status, response = self.app.pause_job(job_id, actor=self._current_actor())
            self._write_json(status, response)
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/v1/manuscripts/"):
            manuscript_id = path.rsplit("/", 1)[-1]
            try:
                payload = self._read_json_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            status, response = self.app.update_manuscript(manuscript_id, payload, actor=self._current_actor())
            self._write_json(status, response)
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/v1/manuscripts/"):
            manuscript_id = path.rsplit("/", 1)[-1]
            status, response = self.app.delete_manuscript(manuscript_id, actor=self._current_actor())
            self._write_json(status, response)
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ManuscriptPrep gateway API.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8765, help="Bind port")
    parser.add_argument("--jobs-root", default="work/gateway_jobs", help="Directory used for persistent job records")
    parser.add_argument(
        "--runtime-root",
        default=None,
        help="Directory used for gateway runtime artifacts such as command/stdout/stderr captures",
    )
    parser.add_argument(
        "--store-backend",
        choices=["file", "postgres"],
        default=os.environ.get("MANUSCRIPTPREP_STORE_BACKEND", "file"),
        help="Persistent store backend for gateway jobs",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("MANUSCRIPTPREP_DATABASE_URL"),
        help="PostgreSQL connection string used when --store-backend=postgres",
    )
    parser.add_argument(
        "--postgres-schema",
        default=os.environ.get("MANUSCRIPTPREP_POSTGRES_SCHEMA", "public"),
        help="PostgreSQL schema used for gateway job tables",
    )
    parser.add_argument(
        "--auth-required",
        action="store_true",
        default=os.environ.get("MANUSCRIPTPREP_AUTH_REQUIRED", "").lower() in {"1", "true", "yes"},
        help="Require API token authentication for /v1 routes",
    )
    parser.add_argument(
        "--bootstrap-admin-username",
        default=os.environ.get("MANUSCRIPTPREP_BOOTSTRAP_ADMIN_USERNAME", "admin"),
        help="Bootstrap admin username used with --bootstrap-admin-token",
    )
    parser.add_argument(
        "--bootstrap-admin-token",
        default=os.environ.get("MANUSCRIPTPREP_BOOTSTRAP_ADMIN_TOKEN"),
        help="Bootstrap admin API token created on gateway startup",
    )
    parser.add_argument(
        "--bootstrap-config-profile-name",
        default=os.environ.get("MANUSCRIPTPREP_BOOTSTRAP_CONFIG_PROFILE_NAME"),
        help="Optional config profile name to bootstrap on gateway startup",
    )
    parser.add_argument(
        "--bootstrap-config-profile-path",
        default=os.environ.get("MANUSCRIPTPREP_BOOTSTRAP_CONFIG_PROFILE_PATH"),
        help="Optional config profile path to bootstrap on gateway startup",
    )
    parser.add_argument(
        "--bootstrap-config-profile-version",
        default=os.environ.get("MANUSCRIPTPREP_BOOTSTRAP_CONFIG_PROFILE_VERSION", "v1"),
        help="Version label for the bootstrapped config profile",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    jobs_root = Path(args.jobs_root)
    runtime_root = Path(args.runtime_root).expanduser() if args.runtime_root else jobs_root / "runtime"
    store = create_job_store(
        backend=args.store_backend,
        jobs_root=jobs_root,
        database_url=args.database_url,
        postgres_schema=args.postgres_schema,
    )
    handler = GatewayHandler
    handler.app = GatewayAPI(
        store=store,
        runtime_root=runtime_root,
        auth_required=args.auth_required,
        bootstrap_username=args.bootstrap_admin_username,
        bootstrap_token=args.bootstrap_admin_token,
        bootstrap_config_profile_name=args.bootstrap_config_profile_name,
        bootstrap_config_profile_path=args.bootstrap_config_profile_path,
        bootstrap_config_profile_version=args.bootstrap_config_profile_version,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    emit_runtime_event(
        "gateway-api",
        "startup",
        host=args.host,
        port=args.port,
        store_backend=store.__class__.__name__,
        auth_required=args.auth_required,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
