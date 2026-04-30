from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

import manuscriptprep.dependencies as deps
import manuscriptprep_orchestrator_tui_refactored as orchestrator


pytestmark = pytest.mark.unit


def test_check_dependencies_reports_missing_python_system_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "module_is_available", lambda name: name == "rich")
    monkeypatch.setattr(deps, "binary_path", lambda name: "/usr/bin/ollama" if name == "ollama" else None)
    monkeypatch.setattr(deps, "probe_ollama_inventory", lambda *_args, **_kwargs: (False, [], "ollama is offline"))

    report = deps.check_dependencies(
        ollama_bin="ollama",
        ollama_host=None,
        required_python_modules=("yaml", "rich"),
        required_system_binaries=("ollama", "pdftotext"),
        required_models=("manuscriptprep-structure",),
    )

    missing = {(item.category, item.name) for item in report.missing_items}
    assert ("python", "yaml") in missing
    assert ("system", "pdftotext") in missing
    assert ("ollama", "server") in missing
    assert ("model", "manuscriptprep-structure") in missing


def test_dependency_preflight_render_includes_install_action() -> None:
    report = deps.DependencyReport(
        checked_at="2026-04-30T00:00:00+00:00",
        items=[
            deps.DependencyItem(
                category="system",
                name="pdftotext",
                status="missing",
                detail="Missing system binary: pdftotext",
                remediation="Run the installer",
            )
        ],
    )
    backend_report = deps.BackendDiagnosticReport(
        checked_at="2026-04-30T00:00:00+00:00",
        platform_name="Linux",
        machine="x86_64",
        preferred_backend="cpu",
        items=[],
    )

    console = Console(record=True, width=120)
    console.print(orchestrator.render_dependency_preflight(report, backend_report))
    output = console.export_text()

    assert "Dependency Preflight" in output
    assert "install missing dependencies" in output.lower()
    assert "pdftotext" in output
    assert "Inference Backend Diagnostics" in output


def test_probe_inference_backends_prefers_cuda_when_nvidia_gpu_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps.platform, "system", lambda: "Linux")
    monkeypatch.setattr(deps.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(deps, "binary_path", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None)

    def fake_run(cmd, capture_output=False, text=False, check=False, timeout=0):
        if cmd[0].endswith("nvidia-smi"):
            return type("Completed", (), {"returncode": 0, "stdout": "RTX 4090, 555.12\n", "stderr": ""})()
        raise AssertionError(f"Unexpected probe command: {cmd}")

    monkeypatch.setattr(deps.subprocess, "run", fake_run)

    report = deps.probe_inference_backends()

    assert report.preferred_backend == "cuda"
    assert any(item.category == "nvidia" and item.status == "ok" for item in report.items)
    assert any(item.category == "fallback" for item in report.items)


def test_backend_report_table_renders_likely_backend() -> None:
    report = deps.BackendDiagnosticReport(
        checked_at="2026-04-30T00:00:00+00:00",
        platform_name="Darwin",
        machine="arm64",
        preferred_backend="metal",
        items=[
            deps.BackendDiagnosticItem(
                category="apple",
                name="metal",
                status="ok",
                detail="Apple Silicon host detected.",
                recommendation="Metal is the expected local inference path.",
            )
        ],
    )

    console = Console(record=True, width=120)
    console.print(orchestrator.backend_report_to_table(report))
    output = console.export_text()

    assert "Inference Backend Diagnostics" in output
    assert "Likely backend" in output
    assert "METAL" in output


def test_run_dependency_installer_executes_installer_script(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    install_dir = repo_root / "install"
    install_dir.mkdir(parents=True)
    (install_dir / "install.py").write_text("print('installer')\n", encoding="utf-8")

    seen: dict[str, list[str]] = {}

    class FakeStdout:
        def __iter__(self):
            return iter(["installing\n", "done\n"])

    class FakePopen:
        def __init__(self, cmd, cwd=None, stdout=None, stderr=None, text=None):
            seen["cmd"] = list(cmd)
            seen["cwd"] = [cwd]
            self.stdout = FakeStdout()

        def wait(self):
            return 0

    monkeypatch.setattr(orchestrator.subprocess, "Popen", FakePopen)

    console = Console(record=True, width=120)
    logger = orchestrator.JsonlLogger(tmp_path / "orchestrator.log.jsonl", run_id="test-run")
    rc = orchestrator.run_dependency_installer(console, repo_root, logger)

    assert rc == 0
    assert seen["cmd"][0] == orchestrator.sys.executable
    assert seen["cmd"][1].endswith("install.py")
    assert seen["cwd"][0] == str(repo_root) or seen["cwd"][0] == repo_root
