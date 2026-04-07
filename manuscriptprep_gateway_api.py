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
import hashlib
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from manuscriptprep.api_models import JobCreateRequest, UserRecord, to_dict, utc_now_iso
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
        if bootstrap_token:
            username = bootstrap_username or "admin"
            self.store.upsert_user(username=username, role=bootstrap_role, api_token=bootstrap_token)
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
        return HTTPStatus.OK, {"manuscripts": [to_dict(item) for item in manuscripts]}

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
        return HTTPStatus.CREATED, to_dict(manuscript)

    def upload_manuscript(self, *, filename: str, body: bytes, actor: Optional[UserRecord] = None) -> Tuple[int, Dict[str, Any]]:
        allowed, error = self._require_actor(actor)
        if not allowed:
            return error
        if not filename:
            return HTTPStatus.BAD_REQUEST, {"error": "Missing required upload filename"}
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

        if path == "/v1/pipelines":
            status, payload = self.app.list_pipelines(actor=self._current_actor())
            self._write_json(status, payload)
            return

        if path == "/v1/manuscripts":
            status, payload = self.app.list_manuscripts(actor=self._current_actor())
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
                actor=self._current_actor(),
            )
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
