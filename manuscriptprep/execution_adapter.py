"""Execution adapter for launching existing CLI stages behind the gateway."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from manuscriptprep.api_models import ArtifactRef, JobRecord, utc_now_iso
from manuscriptprep.config import load_config
from manuscriptprep.paths import build_paths


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CommandExecution:
    exit_code: int
    stdout_path: Path
    stderr_path: Path
    command_path: Path
    stdout: str
    stderr: str


class ExecutionAdapter:
    def __init__(
        self,
        repo_root: Path | None = None,
        python_bin: str | None = None,
        env: dict[str, str] | None = None,
        runtime_root: Path | None = None,
    ) -> None:
        self.repo_root = repo_root or REPO_ROOT
        self.python_bin = python_bin or sys.executable
        self.env = env or os.environ.copy()
        self.runtime_root = (runtime_root or (self.repo_root / "work" / "gateway_jobs" / "runtime")).expanduser()

    def run_job(self, job: JobRecord) -> tuple[JobRecord, list[ArtifactRef]]:
        if job.pipeline == "manuscript-prep":
            return self._run_full_pipeline(job)
        if job.pipeline == "ingest":
            return self._run_ingest(job)
        if job.pipeline == "orchestrate":
            return self._run_orchestrate(job)
        if job.pipeline == "merge":
            return self._run_merge(job)
        if job.pipeline == "resolve":
            return self._run_resolve(job)
        if job.pipeline == "report":
            return self._run_report(job)
        raise ValueError(f"Execution adapter does not yet support pipeline: {job.pipeline}")

    def _stage_run(self, job: JobRecord, stage_name: str):
        for stage in job.stage_runs:
            if stage.name == stage_name:
                return stage
        raise ValueError(f"Unknown stage on job: {stage_name}")

    def _stage_runtime_dir(self, job: JobRecord, stage_name: str) -> Path:
        path = self.runtime_root / job.job_id / stage_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _record_stage_execution(
        self,
        job: JobRecord,
        stage_name: str,
        cmd: list[str],
        result: CommandExecution,
    ) -> list[ArtifactRef]:
        stage = self._stage_run(job, stage_name)
        stage.command = list(cmd)
        stage.exit_code = result.exit_code
        stage.stdout_path = str(result.stdout_path)
        stage.stderr_path = str(result.stderr_path)

        return [
            ArtifactRef(
                name=f"{stage_name}_command",
                path=str(result.command_path),
                kind="json",
                stage=stage_name,
            ),
            ArtifactRef(
                name=f"{stage_name}_stdout",
                path=str(result.stdout_path),
                kind="text",
                stage=stage_name,
                metadata={"bytes": result.stdout_path.stat().st_size},
            ),
            ArtifactRef(
                name=f"{stage_name}_stderr",
                path=str(result.stderr_path),
                kind="text",
                stage=stage_name,
                metadata={"bytes": result.stderr_path.stat().st_size},
            ),
        ]

    def _run_command(self, job: JobRecord, stage_name: str, cmd: list[str], error_message: str) -> CommandExecution:
        runtime_dir = self._stage_runtime_dir(job, stage_name)
        stdout_path = runtime_dir / "stdout.txt"
        stderr_path = runtime_dir / "stderr.txt"
        command_path = runtime_dir / "command.json"
        result = subprocess.run(
            cmd,
            cwd=str(self.repo_root),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        command_path.write_text(
            json.dumps(
                {
                    "stage": stage_name,
                    "cwd": str(self.repo_root),
                    "exit_code": result.returncode,
                    "command": cmd,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or error_message)
        return CommandExecution(
            exit_code=result.returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command_path=command_path,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _mark_stage_running(self, job: JobRecord, stage_name: str) -> None:
        now = utc_now_iso()
        job.status = "running"
        job.updated_at = now
        for stage in job.stage_runs:
            if stage.name == stage_name:
                stage.status = "running"
                stage.started_at = stage.started_at or now
                stage.error = None
                return
        raise ValueError(f"Unknown stage on job: {stage_name}")

    def _mark_stage_succeeded(self, job: JobRecord, stage_name: str) -> JobRecord:
        updated = job
        updated.updated_at = utc_now_iso()
        for stage in updated.stage_runs:
            if stage.name == stage_name:
                stage.status = "succeeded"
                stage.started_at = stage.started_at or updated.updated_at
                stage.finished_at = updated.updated_at
                stage.error = None
                break
        if all(stage.status == "succeeded" for stage in updated.stage_runs):
            updated.status = "succeeded"
        return updated

    def _mark_stage_failed(self, job: JobRecord, stage_name: str, message: str) -> JobRecord:
        updated = job
        updated.status = "failed"
        updated.updated_at = utc_now_iso()
        for stage in updated.stage_runs:
            if stage.name == stage_name:
                stage.status = "failed"
                stage.finished_at = updated.updated_at
                stage.error = message
                break
        return updated

    def _slugify(self, value: str) -> str:
        text = value.lower()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s\-]+", "_", text)
        text = re.sub(r"_+", "_", text)
        return text.strip("_")

    def _resolve_pipeline_layout(self, job: JobRecord) -> dict[str, Path]:
        book_slug = job.book_slug or self._slugify(job.title or "")
        if not book_slug:
            raise ValueError("Pipeline job requires book_slug or title")

        if job.config_path:
            cfg = load_config(job.config_path)
            paths = build_paths(cfg)
            workdir = Path(paths.workspace_root)
            out_dir = Path(paths.output_root) / book_slug
            merged_dir = Path(paths.merged_root) / book_slug
            resolved_dir = Path(paths.resolved_root) / book_slug
            report_output = Path(paths.reports_root) / f"{book_slug}_report.pdf"
            resolver_model = str(cfg.require("models", "resolver"))
        else:
            workdir = Path(str(job.options.get("workdir") or "work"))
            out_dir = Path(str(job.options.get("output_dir") or (Path("out") / book_slug)))
            merged_dir = Path(str(job.options.get("merged_dir") or (Path("merged") / book_slug)))
            resolved_dir = Path(str(job.options.get("resolved_dir") or (Path("resolved") / book_slug)))
            report_output = Path(str(job.options.get("report_output") or (Path("reports") / f"{book_slug}_report.pdf")))
            resolver_model = str(job.options.get("model") or job.options.get("resolver_model") or "manuscriptprep-resolver")

        return {
            "book_slug": book_slug,
            "workdir": workdir,
            "chunk_dir": workdir / "chunks" / book_slug,
            "chunk_manifest": workdir / "manifests" / book_slug / "chunk_manifest.json",
            "out_dir": out_dir,
            "merged_dir": merged_dir,
            "resolved_dir": resolved_dir,
            "report_output": report_output,
            "resolver_model": resolver_model,
        }

    def _run_ingest(self, job: JobRecord) -> tuple[JobRecord, list[ArtifactRef]]:
        if not job.input_path:
            raise ValueError("Ingest jobs require input_path")
        if not job.title:
            raise ValueError("Ingest jobs require title")

        workdir = job.options.get("workdir")
        if not workdir:
            raise ValueError("Ingest jobs require options.workdir")

        cmd = [
            self.python_bin,
            "manuscriptprep_ingest.py",
            "--input",
            str(job.input_path),
            "--workdir",
            str(workdir),
            "--title",
            str(job.title),
        ]
        if job.config_path:
            cmd.extend(["--config", str(job.config_path)])
        if job.options.get("chunk_words") is not None:
            cmd.extend(["--chunk-words", str(job.options["chunk_words"])])
        if job.options.get("min_chunk_words") is not None:
            cmd.extend(["--min-chunk-words", str(job.options["min_chunk_words"])])
        if job.options.get("max_chunk_words") is not None:
            cmd.extend(["--max-chunk-words", str(job.options["max_chunk_words"])])
        if job.options.get("force_ocr"):
            cmd.append("--force-ocr")

        result = self._run_command(job, "ingest", cmd, "Ingest execution failed")

        book_slug = job.book_slug or ""
        workdir_path = Path(str(workdir))
        manifests_dir = workdir_path / "manifests" / book_slug
        chunk_dir = workdir_path / "chunks" / book_slug
        cleaned_path = workdir_path / "cleaned" / book_slug / "clean.txt"
        raw_path = workdir_path / "extracted" / book_slug / "raw.txt"

        artifacts = self._record_stage_execution(job, "ingest", cmd, result) + [
            ArtifactRef(name="raw_text", path=str(raw_path), kind="text", stage="ingest"),
            ArtifactRef(name="clean_text", path=str(cleaned_path), kind="text", stage="ingest"),
            ArtifactRef(name="chunk_dir", path=str(chunk_dir), kind="directory", stage="ingest"),
            ArtifactRef(name="chunk_manifest", path=str(manifests_dir / "chunk_manifest.json"), kind="json", stage="ingest"),
            ArtifactRef(name="ingest_manifest", path=str(manifests_dir / "ingest_manifest.json"), kind="json", stage="ingest"),
        ]

        return self._mark_stage_succeeded(job, "ingest"), artifacts

    def _run_orchestrate(self, job: JobRecord) -> tuple[JobRecord, list[ArtifactRef]]:
        input_dir = job.options.get("input_dir")
        output_dir = job.options.get("output_dir")
        if not input_dir or not output_dir:
            raise ValueError("Orchestrate jobs require options.input_dir and options.output_dir")

        cmd = [
            self.python_bin,
            "manuscriptprep_orchestrator_tui_refactored.py",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--no-tui",
        ]
        if job.config_path:
            cmd.extend(["--config", str(job.config_path)])
        if job.book_slug:
            cmd.extend(["--book-slug", str(job.book_slug)])

        result = self._run_command(job, "orchestrate", cmd, "Orchestrator execution failed")

        out_root = Path(str(output_dir))
        artifacts = self._record_stage_execution(job, "orchestrate", cmd, result) + [
            ArtifactRef(name="output_dir", path=str(out_root), kind="directory", stage="orchestrate"),
            ArtifactRef(name="orchestrator_log", path=str(out_root / "orchestrator.log.jsonl"), kind="jsonl", stage="orchestrate"),
        ]
        return self._mark_stage_succeeded(job, "orchestrate"), artifacts

    def _run_merge(self, job: JobRecord) -> tuple[JobRecord, list[ArtifactRef]]:
        input_dir = job.options.get("input_dir")
        output_dir = job.options.get("output_dir")
        if not input_dir or not output_dir:
            raise ValueError("Merge jobs require options.input_dir and options.output_dir")

        cmd = [
            self.python_bin,
            "manuscriptprep_merger.py",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
        ]
        if job.config_path:
            cmd.extend(["--config", str(job.config_path)])
        if job.book_slug:
            cmd.extend(["--book-slug", str(job.book_slug)])
        if job.options.get("chunk_manifest"):
            cmd.extend(["--chunk-manifest", str(job.options["chunk_manifest"])])

        result = self._run_command(job, "merge", cmd, "Merger execution failed")

        merged_root = Path(str(output_dir))
        artifacts = self._record_stage_execution(job, "merge", cmd, result) + [
            ArtifactRef(name="merged_dir", path=str(merged_root), kind="directory", stage="merge"),
            ArtifactRef(name="book_merged", path=str(merged_root / "book_merged.json"), kind="json", stage="merge"),
            ArtifactRef(name="merge_report", path=str(merged_root / "merge_report.json"), kind="json", stage="merge"),
            ArtifactRef(name="conflict_report", path=str(merged_root / "conflict_report.json"), kind="json", stage="merge"),
        ]
        return self._mark_stage_succeeded(job, "merge"), artifacts

    def _run_resolve(self, job: JobRecord) -> tuple[JobRecord, list[ArtifactRef]]:
        input_dir = job.options.get("input_dir")
        output_dir = job.options.get("output_dir")
        model = job.options.get("model") or job.options.get("resolver_model") or job.options.get("model_name")
        if not input_dir or not output_dir:
            raise ValueError("Resolve jobs require options.input_dir and options.output_dir")

        cmd = [
            self.python_bin,
            "manuscriptprep_resolver.py",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
        ]
        if job.config_path:
            cmd.extend(["--config", str(job.config_path)])
        if job.book_slug:
            cmd.extend(["--book-slug", str(job.book_slug)])
        if model:
            cmd.extend(["--model", str(model)])

        result = self._run_command(job, "resolve", cmd, "Resolver execution failed")

        resolved_root = Path(str(output_dir))
        artifacts = self._record_stage_execution(job, "resolve", cmd, result) + [
            ArtifactRef(name="resolved_dir", path=str(resolved_root), kind="directory", stage="resolve"),
            ArtifactRef(name="book_resolved", path=str(resolved_root / "book_resolved.json"), kind="json", stage="resolve"),
            ArtifactRef(name="resolution_map", path=str(resolved_root / "resolution_map.json"), kind="json", stage="resolve"),
            ArtifactRef(name="resolution_report", path=str(resolved_root / "resolution_report.json"), kind="json", stage="resolve"),
        ]
        return self._mark_stage_succeeded(job, "resolve"), artifacts

    def _run_report(self, job: JobRecord) -> tuple[JobRecord, list[ArtifactRef]]:
        input_dir = job.options.get("input_dir")
        output_path = job.options.get("output_path") or job.options.get("output")
        if not input_dir or not output_path:
            raise ValueError("Report jobs require options.input_dir and options.output_path")

        cmd = [
            self.python_bin,
            "manuscriptprep_pdf_report.py",
            "--input-dir",
            str(input_dir),
            "--output",
            str(output_path),
        ]
        if job.title:
            cmd.extend(["--title", str(job.title)])
        if job.config_path:
            cmd.extend(["--config", str(job.config_path)])
        if job.book_slug:
            cmd.extend(["--book-slug", str(job.book_slug)])
        if job.options.get("subtitle"):
            cmd.extend(["--subtitle", str(job.options["subtitle"])])

        result = self._run_command(job, "report", cmd, "Report execution failed")

        report_path = Path(str(output_path))
        artifacts = self._record_stage_execution(job, "report", cmd, result) + [
            ArtifactRef(name="report_pdf", path=str(report_path), kind="pdf", stage="report"),
        ]
        return self._mark_stage_succeeded(job, "report"), artifacts

    def _run_full_pipeline(self, job: JobRecord) -> tuple[JobRecord, list[ArtifactRef]]:
        if not job.input_path:
            raise ValueError("Pipeline jobs require input_path")
        if not job.title:
            raise ValueError("Pipeline jobs require title")

        layout = self._resolve_pipeline_layout(job)
        book_slug = str(layout["book_slug"])
        all_artifacts: list[ArtifactRef] = []

        try:
            self._mark_stage_running(job, "ingest")
            ingest_job = JobRecord(
                **{
                    **job.__dict__,
                    "pipeline": "ingest",
                    "book_slug": book_slug,
                    "stage_runs": [job.stage_runs[0]],
                    "options": {
                        **job.options,
                        "workdir": str(layout["workdir"]),
                    },
                }
            )
            ingest_job, artifacts = self._run_ingest(ingest_job)
            all_artifacts.extend(artifacts)
            job.stage_runs[0] = ingest_job.stage_runs[0]
        except Exception as exc:
            self._mark_stage_failed(job, "ingest", str(exc))
            raise

        try:
            self._mark_stage_running(job, "orchestrate")
            orch_job = JobRecord(
                **{
                    **job.__dict__,
                    "pipeline": "orchestrate",
                    "book_slug": book_slug,
                    "stage_runs": [job.stage_runs[1]],
                    "options": {
                        **job.options,
                        "input_dir": str(layout["chunk_dir"]),
                        "output_dir": str(layout["out_dir"]),
                    },
                }
            )
            orch_job, artifacts = self._run_orchestrate(orch_job)
            all_artifacts.extend(artifacts)
            job.stage_runs[1] = orch_job.stage_runs[0]
        except Exception as exc:
            self._mark_stage_failed(job, "orchestrate", str(exc))
            raise

        try:
            self._mark_stage_running(job, "merge")
            merge_job = JobRecord(
                **{
                    **job.__dict__,
                    "pipeline": "merge",
                    "book_slug": book_slug,
                    "stage_runs": [job.stage_runs[2]],
                    "options": {
                        **job.options,
                        "input_dir": str(layout["out_dir"]),
                        "output_dir": str(layout["merged_dir"]),
                        "chunk_manifest": str(layout["chunk_manifest"]),
                    },
                }
            )
            merge_job, artifacts = self._run_merge(merge_job)
            all_artifacts.extend(artifacts)
            job.stage_runs[2] = merge_job.stage_runs[0]
        except Exception as exc:
            self._mark_stage_failed(job, "merge", str(exc))
            raise

        try:
            self._mark_stage_running(job, "resolve")
            resolve_job = JobRecord(
                **{
                    **job.__dict__,
                    "pipeline": "resolve",
                    "book_slug": book_slug,
                    "stage_runs": [job.stage_runs[3]],
                    "options": {
                        **job.options,
                        "input_dir": str(layout["merged_dir"]),
                        "output_dir": str(layout["resolved_dir"]),
                        "model": str(layout["resolver_model"]),
                    },
                }
            )
            resolve_job, artifacts = self._run_resolve(resolve_job)
            all_artifacts.extend(artifacts)
            job.stage_runs[3] = resolve_job.stage_runs[0]
        except Exception as exc:
            self._mark_stage_failed(job, "resolve", str(exc))
            raise

        try:
            self._mark_stage_running(job, "report")
            report_job = JobRecord(
                **{
                    **job.__dict__,
                    "pipeline": "report",
                    "book_slug": book_slug,
                    "stage_runs": [job.stage_runs[4]],
                    "options": {
                        **job.options,
                        "input_dir": str(layout["merged_dir"]),
                        "output_path": str(layout["report_output"]),
                    },
                }
            )
            report_job, artifacts = self._run_report(report_job)
            all_artifacts.extend(artifacts)
            job.stage_runs[4] = report_job.stage_runs[0]
        except Exception as exc:
            self._mark_stage_failed(job, "report", str(exc))
            raise

        job.status = "succeeded"
        job.updated_at = utc_now_iso()
        return job, all_artifacts
