from __future__ import annotations

import json
import pytest

from manuscriptprep.execution_adapter import ExecutionAdapter
from manuscriptprep.job_worker import JobWorker
from manuscriptprep.job_store import JobStore
from manuscriptprep_gateway_api import GatewayAPI


pytestmark = pytest.mark.integration


def test_gateway_api_exposes_health_pipelines_and_jobs(tmp_path) -> None:
    app = GatewayAPI(store=JobStore(root=tmp_path / "jobs"))

    status, health = app.health()
    assert status == 200
    assert health["service"] == "gateway-api"

    status, ready = app.ready()
    assert status == 200
    assert ready["status"] == "ready"

    status, system = app.system_status()
    assert status == 200
    assert system["ready"] is True
    assert system["queue"]["total"] == 0

    status, pipelines = app.list_pipelines()
    assert status == 200
    assert "manuscript-prep" in [item["pipeline"] for item in pipelines["pipelines"]]

    status, created = app.create_job({"pipeline": "manuscript-prep", "book_slug": "treasure_island", "title": "Treasure Island"})
    assert status == 201
    assert created["status"] == "queued"
    assert created["stage_runs"][0]["name"] == "ingest"

    job_id = created["job_id"]
    status, fetched = app.get_job(job_id)
    assert status == 200
    assert fetched["job_id"] == job_id

    status, jobs = app.list_jobs()
    assert status == 200
    assert len(jobs["jobs"]) == 1


def test_gateway_api_registers_logs_in_and_returns_current_user(tmp_path) -> None:
    app = GatewayAPI(store=JobStore(root=tmp_path / "jobs"), auth_required=True)

    status, registered = app.register_user({"username": "alice", "password": "supersecret1"})
    assert status == 201
    assert registered["user"]["username"] == "alice"
    assert registered["api_token"]

    stored = app.store.get_user_by_username("alice")
    assert stored is not None
    assert stored.password_hash is not None
    assert stored.password_hash != "supersecret1"

    status, duplicate = app.register_user({"username": "alice", "password": "supersecret1"})
    assert status == 409
    assert duplicate["error"] == "username is already registered"

    status, invalid = app.login_user({"username": "alice", "password": "wrongpass"})
    assert status == 401
    assert invalid["error"] == "Invalid username or password"

    status, logged_in = app.login_user({"username": "alice", "password": "supersecret1"})
    assert status == 200
    actor = app.authenticate(logged_in["api_token"])
    assert actor is not None

    status, me = app.current_user(actor)
    assert status == 200
    assert me["user"]["username"] == "alice"
    assert "api_token" not in me["user"]


def test_gateway_api_persists_and_runs_ingest_jobs(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "book_slug": "treasure_island",
            "title": "Treasure Island",
            "input_path": str(sample_pdf),
            "options": {
                "workdir": str(tmp_path / "work"),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
            },
        }
    )
    assert status == 201
    job_id = created["job_id"]

    import os
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = test_env["PATH"]
    try:
        status, queued = app.run_job(job_id)
        assert status == 202
        assert queued["status"] == "queued"
        assert worker.process_next_job() is True
    finally:
        os.environ["PATH"] = old_path

    status, ran = app.get_job(job_id)
    assert status == 200
    assert status == 200
    assert ran["status"] == "succeeded"
    assert ran["artifacts"]
    assert ran["stage_runs"][0]["command"]
    assert ran["stage_runs"][0]["stdout_path"]
    assert ran["stage_runs"][0]["stderr_path"]
    persisted = store.get_job(job_id)
    assert persisted is not None
    assert persisted.status == "succeeded"
    assert persisted.artifacts[0].stage == "ingest"

    status, system = app.system_status()
    assert status == 200
    assert system["queue"]["succeeded"] == 1
    assert any(item["worker_id"] == worker.worker_id for item in system["workers"])

    status, artifact = app.get_job_artifact(job_id, "ingest_stdout")
    assert status == 200
    assert artifact["exists"] is True
    assert "preview" in artifact
    assert "sha256" in artifact["artifact"]["metadata"]

    status, artifact_index = app.list_job_artifact_index(job_id)
    assert status == 200
    assert {item["name"] for item in artifact_index["artifacts"]} >= {"ingest_stdout", "ingest_stderr", "ingest_command"}


def test_gateway_api_can_cancel_jobs(tmp_path) -> None:
    app = GatewayAPI(store=JobStore(root=tmp_path / "jobs"))

    status, created = app.create_job({"pipeline": "ingest", "book_slug": "treasure_island", "title": "Treasure Island"})
    assert status == 201

    status, cancelled = app.cancel_job(created["job_id"])
    assert status == 202
    assert cancelled["status"] == "cancelled"

    status, created = app.create_job({"pipeline": "orchestrate", "book_slug": "treasure_island", "title": "Treasure Island"})
    assert status == 201
    running = app.store.get_job(created["job_id"])
    assert running is not None
    running.status = "running"
    running.stage_runs[0].status = "running"
    app.store.update_job(running)

    status, cancel_requested = app.cancel_job(created["job_id"])
    assert status == 202
    assert cancel_requested["status"] == "cancel_requested"
    assert cancel_requested["stage_runs"][0]["error"] == "Cancelled by user"

    status, system = app.system_status()
    assert status == 200
    assert system["queue"]["cancel_requested"] == 1


def test_job_worker_finalizes_stale_cancel_requested_jobs(tmp_path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    worker = JobWorker(store=store, adapter=ExecutionAdapter(), poll_interval=0.01, cancel_grace_seconds=0)

    status, created = GatewayAPI(store=store).create_job({"pipeline": "orchestrate", "book_slug": "treasure_island", "title": "Treasure Island"})
    assert status == 201
    running = store.get_job(created["job_id"])
    assert running is not None
    running.status = "cancel_requested"
    running.stage_runs[0].status = "running"
    running.options["_cancel_requested_at"] = "2026-04-09T09:59:00+00:00"
    store.update_job(running)

    worker.recover_stale_jobs()

    refreshed = store.get_job(created["job_id"])
    assert refreshed is not None
    assert refreshed.status == "cancelled"
    assert refreshed.stage_runs[0].status == "cancelled"


def test_gateway_api_exposes_latest_ingest_summary_and_manuscript_ingest_results(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    status, manuscript = app.create_manuscript(
        {
            "title": "Treasure Island",
            "book_slug": "treasure_island",
            "source_path": str(sample_pdf),
            "file_size_bytes": sample_pdf.stat().st_size,
        }
    )
    assert status == 201

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "manuscript_id": manuscript["manuscript_id"],
            "options": {
                "workdir": str(tmp_path / "work"),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
            },
        }
    )
    assert status == 201

    import os
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = test_env["PATH"]
    try:
        status, queued = app.run_job(created["job_id"])
        assert status == 202
        assert queued["status"] == "queued"
        assert worker.process_next_job() is True
    finally:
        os.environ["PATH"] = old_path

    status, manuscripts = app.list_manuscripts()
    assert status == 200
    assert manuscripts["manuscripts"][0]["latest_ingest"]["status"] == "succeeded"
    assert manuscripts["manuscripts"][0]["latest_ingest"]["finished_at"] is not None

    status, ingest_results = app.get_manuscript_ingest_results(manuscript["manuscript_id"])
    assert status == 200
    assert ingest_results["ingest_manifest"]["content"]["classification"]["pdf_type"] in {"text", "image_or_mixed"}
    assert ingest_results["chunk_manifest"]["content"]["chunk_count"] >= 1
    assert ingest_results["raw_text"]["content"]
    assert ingest_results["clean_text"]["content"]
    assert "treasure_island" in ingest_results["ingest_manifest"]["artifact"]["path"]


def test_gateway_api_exposes_orchestrate_progress_from_log(tmp_path) -> None:
    app = GatewayAPI(store=JobStore(root=tmp_path / "jobs"))
    input_dir = tmp_path / "chunks"
    output_dir = tmp_path / "out"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    for index in range(1, 4):
        (input_dir / f"chunk_{index:03d}.txt").write_text(f"chunk {index}\n", encoding="utf-8")

    status, created = app.create_job(
        {
            "pipeline": "orchestrate",
            "book_slug": "treasure_island",
            "options": {
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
            },
        }
    )
    assert status == 201

    persisted = app.store.get_job(created["job_id"])
    assert persisted is not None
    persisted.created_at = "2026-04-09T09:59:00+00:00"
    persisted.updated_at = "2026-04-09T09:59:00+00:00"
    persisted.status = "running"
    persisted.stage_runs[0].status = "running"
    persisted.stage_runs[0].started_at = "2026-04-09T09:59:30+00:00"
    app.store.update_job(persisted)

    log_path = output_dir / "orchestrator.log.jsonl"
    log_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-04-09T10:00:00+00:00",
                        "event_type": "chunk_start",
                        "message": "Processing chunk",
                        "chunk": "chunk_001",
                        "step": "loading excerpt",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-09T10:00:10+00:00",
                        "event_type": "pass_start",
                        "message": "Starting pass",
                        "chunk": "chunk_001",
                        "pass": "structure",
                        "step": "starting structure",
                        "model": "manuscriptprep-structure",
                        "attempt": 1,
                        "idle_timeout_s": 180,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-09T10:01:30+00:00",
                        "event_type": "pass_success",
                        "message": "Pass completed successfully",
                        "chunk": "chunk_001",
                        "pass": "structure",
                        "step": "completed structure",
                        "model": "manuscriptprep-structure",
                        "attempt": 1,
                        "reported_tps": 44.2,
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-04-09T10:01:31+00:00",
                        "event_type": "pass_start",
                        "message": "Starting pass",
                        "chunk": "chunk_001",
                        "pass": "dialogue",
                        "step": "starting dialogue",
                        "model": "manuscriptprep-dialogue",
                        "attempt": 1,
                        "idle_timeout_s": 180,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    status, progress = app.get_job_progress(created["job_id"])
    assert status == 200
    assert progress["available"] is True
    assert progress["chunks_total"] == 3
    assert progress["current_chunk"] == "chunk_001"
    assert progress["current_chunk_index"] == 1
    assert progress["current_pass"] == "dialogue"
    assert progress["current_pass_index"] == 2
    assert progress["current_model"] == "manuscriptprep-dialogue"
    assert progress["reported_tps"] == 44.2
    assert progress["recent_events"]


def test_gateway_api_ingest_artifacts_follow_manuscript_slug(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    status, manuscript = app.create_manuscript(
        {
            "title": "Treasure Island",
            "book_slug": "treasure_island_by_robert_louis_stevenson",
            "source_path": str(sample_pdf),
            "file_size_bytes": sample_pdf.stat().st_size,
        }
    )
    assert status == 201

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "manuscript_id": manuscript["manuscript_id"],
            "options": {
                "workdir": str(tmp_path / "work"),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
            },
        }
    )
    assert status == 201

    import os
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = test_env["PATH"]
    try:
        status, queued = app.run_job(created["job_id"])
        assert status == 202
        assert queued["status"] == "queued"
        assert worker.process_next_job() is True
    finally:
        os.environ["PATH"] = old_path

    status, ingest_results = app.get_manuscript_ingest_results(manuscript["manuscript_id"])
    assert status == 200
    assert "treasure_island_by_robert_louis_stevenson" in ingest_results["ingest_manifest"]["artifact"]["path"]
    assert ingest_results["ingest_manifest"]["exists"] is True
    assert ingest_results["raw_text"]["exists"] is True
    assert ingest_results["clean_text"]["exists"] is True
    assert ingest_results["raw_text"]["content"]
    assert ingest_results["clean_text"]["content"]


def test_gateway_api_downloads_job_artifact(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    status, manuscript = app.create_manuscript(
        {
            "title": "Treasure Island",
            "book_slug": "treasure_island",
            "source_path": str(sample_pdf),
            "file_size_bytes": sample_pdf.stat().st_size,
        }
    )
    assert status == 201

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "manuscript_id": manuscript["manuscript_id"],
            "options": {
                "workdir": str(tmp_path / "work"),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
            },
        }
    )
    assert status == 201

    import os
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = test_env["PATH"]
    try:
        status, queued = app.run_job(created["job_id"])
        assert status == 202
        assert queued["status"] == "queued"
        assert worker.process_next_job() is True
    finally:
        os.environ["PATH"] = old_path

    status, payload, content_type = app.download_job_artifact(created["job_id"], "ingest_manifest")
    assert status == 200
    assert content_type.startswith("application/json")
    assert payload.is_file()
    manifest = json.loads(payload.read_text(encoding="utf-8"))
    assert manifest["book_title"] == "Treasure Island"


def test_gateway_api_updates_and_deletes_manuscripts(tmp_path, sample_pdf) -> None:
    app = GatewayAPI(store=JobStore(root=tmp_path / "jobs"))

    status, manuscript = app.create_manuscript(
        {
            "title": "Treasure Island",
            "book_slug": "treasure_island",
            "source_path": str(sample_pdf),
        }
    )
    assert status == 201

    status, updated = app.update_manuscript(
        manuscript["manuscript_id"],
        {"title": "Treasure Island Revised", "book_slug": "treasure_island_revised"},
    )
    assert status == 200
    assert updated["title"] == "Treasure Island Revised"
    assert updated["book_slug"] == "treasure_island_revised"

    status, deleted = app.delete_manuscript(manuscript["manuscript_id"])
    assert status == 200
    assert deleted["deleted"] is True

    status, manuscripts = app.list_manuscripts()
    assert status == 200
    assert manuscripts["manuscripts"] == []


def test_gateway_api_runs_full_service_sequence(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    book_slug = "treasure_island"
    workdir = tmp_path / "work"
    out_dir = tmp_path / "out" / book_slug
    merged_dir = tmp_path / "merged" / book_slug
    resolved_dir = tmp_path / "resolved" / book_slug
    report_path = tmp_path / "reports" / "treasure_island_report.pdf"

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "book_slug": book_slug,
            "title": "Treasure Island",
            "input_path": str(sample_pdf),
            "options": {
                "workdir": str(workdir),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
            },
        }
    )
    assert status == 201
    status, ingested = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, ingested = app.get_job(created["job_id"])
    assert status == 200
    assert ingested["status"] == "succeeded"

    status, created = app.create_job(
        {
            "pipeline": "orchestrate",
            "book_slug": book_slug,
            "options": {
                "input_dir": str(workdir / "chunks" / book_slug),
                "output_dir": str(out_dir),
            },
        }
    )
    assert status == 201
    status, orchestrated = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, orchestrated = app.get_job(created["job_id"])
    assert status == 200
    assert orchestrated["status"] == "succeeded"

    chunk_manifest = workdir / "manifests" / book_slug / "chunk_manifest.json"
    status, created = app.create_job(
        {
            "pipeline": "merge",
            "book_slug": book_slug,
            "options": {
                "input_dir": str(out_dir),
                "output_dir": str(merged_dir),
                "chunk_manifest": str(chunk_manifest),
            },
        }
    )
    assert status == 201
    status, merged = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, merged = app.get_job(created["job_id"])
    assert status == 200
    assert merged["status"] == "succeeded"
    assert any(item["name"] == "book_merged" for item in merged["artifacts"])

    status, created = app.create_job(
        {
            "pipeline": "resolve",
            "book_slug": book_slug,
            "options": {
                "input_dir": str(merged_dir),
                "output_dir": str(resolved_dir),
                "model": "manuscriptprep-resolver",
            },
        }
    )
    assert status == 201
    status, resolved = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, resolved = app.get_job(created["job_id"])
    assert status == 200
    assert resolved["status"] == "succeeded"
    resolved_book = json.loads((resolved_dir / "book_resolved.json").read_text(encoding="utf-8"))
    assert "characters_resolved" in resolved_book["entities"]

    status, created = app.create_job(
        {
            "pipeline": "report",
            "book_slug": book_slug,
            "title": "Treasure Island",
            "options": {
                "input_dir": str(merged_dir),
                "output_path": str(report_path),
            },
        }
    )
    assert status == 201
    status, reported = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, reported = app.get_job(created["job_id"])
    assert status == 200
    assert reported["status"] == "succeeded"
    assert report_path.exists()


def test_gateway_api_runs_single_end_to_end_pipeline_job(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    book_slug = "treasure_island"
    workdir = tmp_path / "work"

    status, created = app.create_job(
        {
            "pipeline": "manuscript-prep",
            "book_slug": book_slug,
            "title": "Treasure Island",
            "input_path": str(sample_pdf),
            "options": {
                "workdir": str(workdir),
                "chunk_words": 20,
                "min_chunk_words": 5,
                "max_chunk_words": 30,
                "output_dir": str(tmp_path / "out" / book_slug),
                "merged_dir": str(tmp_path / "merged" / book_slug),
                "resolved_dir": str(tmp_path / "resolved" / book_slug),
                "report_output": str(tmp_path / "reports" / "treasure_island_report.pdf"),
                "model": "manuscriptprep-resolver",
            },
        }
    )
    assert status == 201

    status, completed = app.run_job(created["job_id"])
    assert status == 202
    assert worker.process_next_job() is True
    status, completed = app.get_job(created["job_id"])
    assert status == 200
    assert completed["status"] == "succeeded"
    assert [stage["status"] for stage in completed["stage_runs"]] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    artifact_names = {item["name"] for item in completed["artifacts"]}
    assert "chunk_manifest" in artifact_names
    assert "book_merged" in artifact_names
    assert "book_resolved" in artifact_names
    assert "report_pdf" in artifact_names


def test_gateway_api_enforces_auth_and_job_ownership(tmp_path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    app = GatewayAPI(
        store=store,
        auth_required=True,
        bootstrap_username="admin",
        bootstrap_token="admin-token",
    )
    alice = store.upsert_user(username="alice", role="user", api_token="alice-token")
    bob = store.upsert_user(username="bob", role="user", api_token="bob-token")
    admin = app.authenticate("admin-token")
    assert admin is not None

    status, payload = app.list_jobs()
    assert status == 401
    assert payload["error"] == "Authentication required"

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "book_slug": "treasure_island",
            "title": "Treasure Island",
        },
        actor=alice,
    )
    assert status == 201
    assert created["owner_user_id"] == alice.user_id
    assert created["owner_username"] == "alice"

    job_id = created["job_id"]

    status, alice_jobs = app.list_jobs(actor=alice)
    assert status == 200
    assert [job["job_id"] for job in alice_jobs["jobs"]] == [job_id]

    status, bob_jobs = app.list_jobs(actor=bob)
    assert status == 200
    assert bob_jobs["jobs"] == []

    status, forbidden = app.get_job(job_id, actor=bob)
    assert status == 403
    assert forbidden["error"] == "Not authorized for this job"

    status, admin_jobs = app.list_jobs(actor=admin)
    assert status == 200
    assert [job["job_id"] for job in admin_jobs["jobs"]] == [job_id]

    status, system = app.system_status(actor=alice)
    assert status == 403
    assert system["error"] == "Admin access required"

    status, system = app.system_status(actor=admin)
    assert status == 200
    assert system["store_backend"] == "JobStore"


def test_gateway_api_manages_manuscripts_and_config_profiles(tmp_path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    app = GatewayAPI(
        store=store,
        auth_required=True,
        bootstrap_username="admin",
        bootstrap_token="admin-token",
    )
    alice = store.upsert_user(username="alice", role="user", api_token="alice-token")
    admin = app.authenticate("admin-token")
    assert admin is not None

    status, profile = app.create_config_profile(
        {
            "name": "default",
            "config_path": "/tmp/manuscriptprep.yaml",
            "version": "v1",
        },
        actor=admin,
    )
    assert status == 201

    status, forbidden = app.create_config_profile(
        {
            "name": "user-profile",
            "config_path": "/tmp/user.yaml",
            "version": "v1",
        },
        actor=alice,
    )
    assert status == 403
    assert forbidden["error"] == "Admin access required"

    status, manuscript = app.create_manuscript(
        {
            "book_slug": "treasure_island",
            "title": "Treasure Island",
            "source_path": "/tmp/treasure-island.pdf",
        },
        actor=alice,
    )
    assert status == 201

    status, alice_manuscripts = app.list_manuscripts(actor=alice)
    assert status == 200
    assert [item["manuscript_id"] for item in alice_manuscripts["manuscripts"]] == [manuscript["manuscript_id"]]

    status, created = app.create_job(
        {
            "pipeline": "ingest",
            "manuscript_id": manuscript["manuscript_id"],
            "config_profile_id": profile["config_profile_id"],
            "options": {"workdir": str(tmp_path / "work")},
        },
        actor=alice,
    )
    assert status == 201
    assert created["manuscript_id"] == manuscript["manuscript_id"]
    assert created["config_profile_id"] == profile["config_profile_id"]
    assert created["book_slug"] == "treasure_island"
    assert created["title"] == "Treasure Island"
    assert created["input_path"] == "/tmp/treasure-island.pdf"
    assert created["config_path"] == "/tmp/manuscriptprep.yaml"


def test_gateway_api_uploads_and_registers_manuscripts(tmp_path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    app = GatewayAPI(
        store=store,
        auth_required=True,
        bootstrap_username="admin",
        bootstrap_token="admin-token",
    )
    alice = store.upsert_user(username="alice", role="user", api_token="alice-token")

    status, upload = app.upload_manuscript(filename="Novel Draft.pdf", body=b"%PDF-1.4 demo", actor=alice)
    assert status == 201
    assert upload["filename"] == "novel_draft.pdf"
    assert upload["size_bytes"] == len(b"%PDF-1.4 demo")

    status, manuscript = app.create_manuscript(
        {
            "title": "Novel Draft",
            "source_path": upload["path"],
            "file_size_bytes": upload["size_bytes"],
        },
        actor=alice,
    )
    assert status == 201
    assert manuscript["book_slug"] == "novel_draft"
    assert manuscript["file_size_bytes"] == len(b"%PDF-1.4 demo")


def test_gateway_api_stage_jobs_can_derive_defaults_from_manuscript_and_config(tmp_path, sample_pdf, test_env) -> None:
    store = JobStore(root=tmp_path / "jobs")
    adapter = ExecutionAdapter(env=test_env)
    worker = JobWorker(store=store, adapter=adapter, poll_interval=0.01)
    app = GatewayAPI(store=store)

    workspace_root = tmp_path / "workspace"
    config_path = tmp_path / "manuscriptprep.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: manuscriptprep",
                "paths:",
                f"  repo_root: {tmp_path / 'repo'}",
                f"  workspace_root: {workspace_root}",
                f"  input_root: {workspace_root / 'input'}",
                f"  extracted_root: {workspace_root / 'extracted'}",
                f"  cleaned_root: {workspace_root / 'cleaned'}",
                f"  chunks_root: {workspace_root / 'chunks'}",
                f"  output_root: {workspace_root / 'out'}",
                f"  merged_root: {workspace_root / 'merged'}",
                f"  resolved_root: {workspace_root / 'resolved'}",
                f"  reports_root: {workspace_root / 'reports'}",
                f"  logs_root: {workspace_root / 'logs'}",
                "models:",
                "  structure: manuscriptprep-structure",
                "  dialogue: manuscriptprep-dialogue",
                "  entities: manuscriptprep-entities",
                "  dossiers: manuscriptprep-dossiers",
                "  resolver: manuscriptprep-resolver",
                "ollama:",
                "  host: http://127.0.0.1:11434",
                "timeouts:",
                "  idle_seconds: 180",
                "  hard_seconds: 900",
                "  retries: 2",
                "  idle_timeout_backoff: 1.5",
                "  max_idle_timeout_seconds: 600",
                "  resolver_timeout_seconds: 180",
                "chunking:",
                "  target_words: 20",
                "  min_words: 5",
                "  max_words: 30",
                "logging:",
                "  level: INFO",
                "  jsonl: true",
                "  console: true",
                "reporting:",
                "  include_resolution: true",
                "  max_biography_entries_per_dossier: 6",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    status, profile = app.create_config_profile(
        {
            "name": "ui-default",
            "config_path": str(config_path),
            "version": "v1",
        }
    )
    assert status == 201
    assert profile["metadata"]["models"]["resolver"] == "manuscriptprep-resolver"

    status, manuscript = app.create_manuscript(
        {
            "title": "Treasure Island",
            "book_slug": "treasure_island",
            "source_path": str(sample_pdf),
            "file_size_bytes": sample_pdf.stat().st_size,
        }
    )
    assert status == 201

    import os
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = test_env["PATH"]
    try:
        for pipeline in ["ingest", "orchestrate", "merge", "resolve", "report"]:
            status, created = app.create_job(
                {
                    "pipeline": pipeline,
                    "manuscript_id": manuscript["manuscript_id"],
                    "config_profile_id": profile["config_profile_id"],
                }
            )
            assert status == 201
            status, _queued = app.run_job(created["job_id"])
            assert status == 202
            assert worker.process_next_job() is True
            status, completed = app.get_job(created["job_id"])
            assert status == 200
            assert completed["status"] == "succeeded"
    finally:
        os.environ["PATH"] = old_path

    report_path = workspace_root / "reports" / "treasure_island_report.pdf"
    assert report_path.exists()


def test_gateway_api_bootstraps_default_config_profile(tmp_path) -> None:
    store = JobStore(root=tmp_path / "jobs")
    config_path = tmp_path / "compose.yaml"
    config_path.write_text(
        "\n".join(
            [
                "project:",
                "  name: manuscriptprep",
                "paths:",
                f"  repo_root: {tmp_path / 'repo'}",
                f"  workspace_root: {tmp_path / 'workspace'}",
                f"  input_root: {tmp_path / 'workspace' / 'input'}",
                f"  extracted_root: {tmp_path / 'workspace' / 'extracted'}",
                f"  cleaned_root: {tmp_path / 'workspace' / 'cleaned'}",
                f"  chunks_root: {tmp_path / 'workspace' / 'chunks'}",
                f"  output_root: {tmp_path / 'workspace' / 'out'}",
                f"  merged_root: {tmp_path / 'workspace' / 'merged'}",
                f"  resolved_root: {tmp_path / 'workspace' / 'resolved'}",
                f"  reports_root: {tmp_path / 'workspace' / 'reports'}",
                f"  logs_root: {tmp_path / 'workspace' / 'logs'}",
                "models:",
                "  structure: manuscriptprep-structure",
                "  dialogue: manuscriptprep-dialogue",
                "  entities: manuscriptprep-entities",
                "  dossiers: manuscriptprep-dossiers",
                "  resolver: manuscriptprep-resolver",
                "ollama:",
                "  host: http://127.0.0.1:11434",
                "timeouts:",
                "  idle_seconds: 180",
                "  hard_seconds: 900",
                "  retries: 2",
                "  idle_timeout_backoff: 1.5",
                "  max_idle_timeout_seconds: 600",
                "  resolver_timeout_seconds: 180",
                "chunking:",
                "  target_words: 1200",
                "  min_words: 800",
                "  max_words: 1500",
                "logging:",
                "  level: INFO",
                "  jsonl: true",
                "  console: true",
                "reporting:",
                "  include_resolution: true",
                "  max_biography_entries_per_dossier: 6",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    app = GatewayAPI(
        store=store,
        bootstrap_config_profile_name="studio-default",
        bootstrap_config_profile_path=str(config_path),
        bootstrap_config_profile_version="v1",
    )

    status, profiles = app.list_config_profiles()
    assert status == 200
    assert profiles["config_profiles"][0]["name"] == "studio-default"
    assert profiles["config_profiles"][0]["metadata"]["models"]["resolver"] == "manuscriptprep-resolver"
