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
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

from manuscriptprep.api_models import JobCreateRequest, to_dict, utc_now_iso
from manuscriptprep.job_store import BaseJobStore
from manuscriptprep.service_registry import get_pipeline_definition, list_pipelines
from manuscriptprep.store_factory import create_job_store


class GatewayAPI:
    def __init__(
        self,
        store: BaseJobStore | None = None,
        runtime_root: Path | None = None,
    ) -> None:
        self.store = store or create_job_store(backend="file", jobs_root=Path("work/gateway_jobs"))
        self.runtime_root = runtime_root or getattr(self.store, "root", Path("work/gateway_jobs")) / "runtime"

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

    def system_status(self) -> Tuple[int, Dict[str, Any]]:
        workers = [to_dict(item) for item in self.store.list_worker_heartbeats()]
        return HTTPStatus.OK, {
            "service": "gateway-api",
            "timestamp": utc_now_iso(),
            "store_backend": self.store.__class__.__name__,
            "ready": self.store.is_ready(),
            "queue": self.store.queue_summary(),
            "workers": workers,
        }

    def list_pipelines(self) -> Tuple[int, Dict[str, Any]]:
        return HTTPStatus.OK, {"pipelines": [to_dict(item) for item in list_pipelines()]}

    def list_jobs(self) -> Tuple[int, Dict[str, Any]]:
        return HTTPStatus.OK, {"jobs": [to_dict(item) for item in self.store.list_jobs()]}

    def get_job(self, job_id: str) -> Tuple[int, Dict[str, Any]]:
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
        return HTTPStatus.OK, to_dict(job)

    def get_job_artifact(self, job_id: str, artifact_name: str) -> Tuple[int, Dict[str, Any]]:
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}

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

    def create_job(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        try:
            request = JobCreateRequest(
                pipeline=str(payload["pipeline"]),
                book_slug=payload.get("book_slug"),
                title=payload.get("title"),
                config_path=payload.get("config_path"),
                input_path=payload.get("input_path"),
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

    def run_job(self, job_id: str) -> Tuple[int, Dict[str, Any]]:
        job = self.store.get_job(job_id)
        if job is None:
            return HTTPStatus.NOT_FOUND, {"error": f"Unknown job: {job_id}"}
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

    def _write_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        if path == "/health":
            status, payload = self.app.health()
            self._write_json(status, payload)
            return

        if path == "/ready":
            status, payload = self.app.ready()
            self._write_json(status, payload)
            return

        if path == "/v1/system/status":
            status, payload = self.app.system_status()
            self._write_json(status, payload)
            return

        if path == "/v1/pipelines":
            status, payload = self.app.list_pipelines()
            self._write_json(status, payload)
            return

        if path == "/v1/jobs":
            status, payload = self.app.list_jobs()
            self._write_json(status, payload)
            return

        if path.startswith("/v1/jobs/") and "/artifacts/" in path:
            parts = path.strip("/").split("/")
            if len(parts) == 5:
                _, _, job_id, _, artifact_name = parts
                status, payload = self.app.get_job_artifact(job_id, artifact_name)
                self._write_json(status, payload)
                return

        if path.startswith("/v1/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            status, payload = self.app.get_job(job_id)
            self._write_json(status, payload)
            return

        self._write_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/v1/jobs":
            try:
                payload = self._read_json_body()
            except (json.JSONDecodeError, ValueError) as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            status, response = self.app.create_job(payload)
            self._write_json(status, response)
            return

        if path.startswith("/v1/jobs/") and path.endswith("/run"):
            job_id = path.split("/")[-2]
            status, response = self.app.run_job(job_id)
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
    handler.app = GatewayAPI(store=store, runtime_root=runtime_root)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Gateway API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
