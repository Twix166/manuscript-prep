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

    console = Console(record=True, width=120)
    console.print(orchestrator.render_dependency_preflight(report))
    output = console.export_text()

    assert "Dependency Preflight" in output
    assert "install missing dependencies" in output.lower()
    assert "pdftotext" in output


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
