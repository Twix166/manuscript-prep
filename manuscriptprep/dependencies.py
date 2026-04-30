"""Shared dependency checks for ManuscriptPrep tooling.

This module is intentionally stdlib-only so it can be imported by the
orchestrator, installer, and diagnostics code without creating a circular
dependency on the UI stack.
"""

from __future__ import annotations

import importlib.util
import json
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request


DEFAULT_PYTHON_MODULES: tuple[str, ...] = ("yaml", "rich")
DEFAULT_SYSTEM_BINARIES: tuple[str, ...] = (
    "ollama",
    "pdftotext",
    "pdfinfo",
    "ocrmypdf",
    "tesseract",
    "ghostscript",
)
DEFAULT_OLLAMA_BASE_MODEL = "qwen3:8b-q4_K_M"
DEFAULT_OLLAMA_MODELS: tuple[str, ...] = (
    "manuscriptprep-structure",
    "manuscriptprep-dialogue",
    "manuscriptprep-entities",
    "manuscriptprep-dossiers",
    "manuscriptprep-resolver",
)


@dataclass
class DependencyItem:
    category: str
    name: str
    status: str  # ok, missing, warning
    detail: str
    remediation: str | None = None


@dataclass
class DependencyReport:
    checked_at: str
    items: list[DependencyItem] = field(default_factory=list)
    installed_models: list[str] = field(default_factory=list)
    ollama_available: bool = False
    ollama_detail: str | None = None

    @property
    def missing_items(self) -> list[DependencyItem]:
        return [item for item in self.items if item.status != "ok"]

    @property
    def has_missing(self) -> bool:
        return any(item.status != "ok" for item in self.items)

    @property
    def missing_count(self) -> int:
        return len(self.missing_items)


@dataclass
class BackendDiagnosticItem:
    category: str
    name: str
    status: str  # ok, warning, info
    detail: str
    recommendation: str | None = None


@dataclass
class BackendDiagnosticReport:
    checked_at: str
    platform_name: str
    machine: str
    preferred_backend: str
    items: list[BackendDiagnosticItem] = field(default_factory=list)

    @property
    def available_items(self) -> list[BackendDiagnosticItem]:
        return [item for item in self.items if item.status == "ok"]

    @property
    def warning_items(self) -> list[BackendDiagnosticItem]:
        return [item for item in self.items if item.status == "warning"]


def module_is_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def binary_path(binary_name: str) -> str | None:
    return shutil.which(binary_name)


def _normalize_model_name(name: str) -> str:
    return name.strip()


def model_matches(installed_name: str, required_name: str) -> bool:
    installed = _normalize_model_name(installed_name)
    required = _normalize_model_name(required_name)
    return installed == required or installed.startswith(required + ":")


def parse_ollama_list_output(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("NAME "):
            continue
        if re.fullmatch(r"-+", stripped):
            continue
        parts = stripped.split()
        if not parts:
            continue
        names.append(parts[0])
    return names


def probe_ollama_inventory(ollama_bin: str, ollama_host: str | None = None) -> tuple[bool, list[str], str | None]:
    if ollama_host:
        request = urllib_request.Request(ollama_host.rstrip("/") + "/api/tags", method="GET")
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - network/runtime dependent
            if binary_path(ollama_bin) is not None:
                return probe_ollama_inventory(ollama_bin, None)
            return False, [], f"Unable to reach Ollama host: {exc}"

        models = payload.get("models", [])
        if not isinstance(models, list):
            if binary_path(ollama_bin) is not None:
                return probe_ollama_inventory(ollama_bin, None)
            return False, [], "Ollama host returned an unexpected payload"
        names = [str(model.get("name", "")).strip() for model in models if isinstance(model, dict) and model.get("name")]
        return True, names, None

    if binary_path(ollama_bin) is None:
        return False, [], f"Missing Ollama binary: {ollama_bin}"

    try:
        completed = subprocess.run(
            [ollama_bin, "list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except Exception as exc:  # pragma: no cover - runtime dependent
        return False, [], f"Unable to query Ollama: {exc}"

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr or stdout or "Ollama is not responding"
        return False, [], detail

    return True, parse_ollama_list_output(completed.stdout), None


def _run_probe_command(cmd: list[str], timeout: int = 10) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except Exception as exc:  # pragma: no cover - runtime dependent
        return False, str(exc)

    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        return False, output or f"{cmd[0]} returned non-zero status"
    return True, output or "available"


def probe_inference_backends() -> BackendDiagnosticReport:
    system_name = platform.system().lower()
    machine = platform.machine().lower()
    items: list[BackendDiagnosticItem] = []
    preferred_backend = "cpu"

    items.append(
        BackendDiagnosticItem(
            category="platform",
            name="host",
            status="info",
            detail=f"{platform.system()} / {platform.machine()}",
        )
    )

    nvidia_bin = binary_path("nvidia-smi")
    if nvidia_bin:
        ok, output = _run_probe_command([
            nvidia_bin,
            "--query-gpu=name,driver_version",
            "--format=csv,noheader",
        ])
        if ok:
            preferred_backend = "cuda"
            items.append(
                BackendDiagnosticItem(
                    category="nvidia",
                    name="cuda",
                    status="ok",
                    detail=f"Detected NVIDIA GPU(s): {output}",
                    recommendation="CUDA is the likely inference path on this host.",
                )
            )
        else:
            items.append(
                BackendDiagnosticItem(
                    category="nvidia",
                    name="cuda",
                    status="warning",
                    detail=f"NVIDIA tooling is present but probing failed: {output}",
                    recommendation="Verify NVIDIA drivers and retry nvidia-smi.",
                )
            )
    else:
        items.append(
            BackendDiagnosticItem(
                category="nvidia",
                name="cuda",
                status="warning",
                detail="nvidia-smi not found",
                recommendation="Install NVIDIA drivers if you expect CUDA acceleration.",
            )
        )

    rocm_bin = binary_path("rocminfo") or binary_path("rocm-smi")
    if rocm_bin:
        ok, output = _run_probe_command([rocm_bin], timeout=15)
        if ok:
            if preferred_backend == "cpu":
                preferred_backend = "rocm"
            items.append(
                BackendDiagnosticItem(
                    category="amd",
                    name="rocm",
                    status="ok",
                    detail=f"AMD ROCm tooling detected: {rocm_bin}",
                    recommendation=output if output != "available" else "ROCm appears usable on this host.",
                )
            )
        else:
            items.append(
                BackendDiagnosticItem(
                    category="amd",
                    name="rocm",
                    status="warning",
                    detail=f"AMD tooling is present but probing failed: {output}",
                    recommendation="Verify ROCm drivers and device access.",
                )
            )
    else:
        items.append(
            BackendDiagnosticItem(
                category="amd",
                name="rocm",
                status="warning",
                detail="rocminfo/rocm-smi not found",
                recommendation="Install ROCm if you expect AMD acceleration.",
            )
        )

    vulkan_bin = binary_path("vulkaninfo")
    if vulkan_bin:
        ok, output = _run_probe_command([vulkan_bin], timeout=15)
        if ok:
            if preferred_backend == "cpu":
                preferred_backend = "vulkan"
            items.append(
                BackendDiagnosticItem(
                    category="vulkan",
                    name="gpu-api",
                    status="ok",
                    detail="Vulkan diagnostics tool detected",
                    recommendation=output if output != "available" else "Vulkan-capable GPU path detected.",
                )
            )
        else:
            items.append(
                BackendDiagnosticItem(
                    category="vulkan",
                    name="gpu-api",
                    status="warning",
                    detail=f"Vulkan tooling is present but probing failed: {output}",
                    recommendation="Check GPU drivers and Vulkan runtime support.",
                )
            )
    else:
        items.append(
            BackendDiagnosticItem(
                category="vulkan",
                name="gpu-api",
                status="warning",
                detail="vulkaninfo not found",
                recommendation="Install Vulkan utilities if you want cross-vendor GPU diagnostics.",
            )
        )

    if system_name == "darwin" and machine in {"arm64", "aarch64"}:
        if preferred_backend == "cpu":
            preferred_backend = "metal"
        items.append(
            BackendDiagnosticItem(
                category="apple",
                name="metal",
                status="ok",
                detail="Apple Silicon host detected; Metal acceleration should be available to Ollama.",
                recommendation="Metal is the expected local inference path on Apple Silicon.",
            )
        )
    elif system_name == "darwin":
        items.append(
            BackendDiagnosticItem(
                category="apple",
                name="metal",
                status="warning",
                detail="Intel macOS host detected; Ollama falls back to CPU on this architecture.",
                recommendation="Use Apple Silicon for local GPU acceleration on macOS.",
            )
        )
    else:
        items.append(
            BackendDiagnosticItem(
                category="apple",
                name="metal",
                status="info",
                detail="Metal is macOS-only; this host is not macOS.",
            )
        )

    if preferred_backend == "cpu":
        items.append(
            BackendDiagnosticItem(
                category="fallback",
                name="cpu",
                status="info",
                detail="No stronger local acceleration path was confirmed; Ollama can still run on CPU.",
                recommendation="CPU fallback is acceptable for diagnostics and lower-volume use, but slower for large books.",
            )
        )
    else:
        items.append(
            BackendDiagnosticItem(
                category="fallback",
                name="cpu",
                status="info",
                detail="CPU fallback remains available if GPU acceleration is unavailable or disabled.",
            )
        )

    from datetime import datetime, timezone

    return BackendDiagnosticReport(
        checked_at=datetime.now(timezone.utc).isoformat(),
        platform_name=platform.system(),
        machine=platform.machine(),
        preferred_backend=preferred_backend,
        items=items,
    )


def check_dependencies(
    *,
    ollama_bin: str = "ollama",
    ollama_host: str | None = None,
    required_python_modules: Sequence[str] = DEFAULT_PYTHON_MODULES,
    required_system_binaries: Sequence[str] = DEFAULT_SYSTEM_BINARIES,
    required_models: Sequence[str] = DEFAULT_OLLAMA_MODELS,
    inventory_probe: Callable[[str, str | None], tuple[bool, list[str], str | None]] | None = None,
) -> DependencyReport:
    items: list[DependencyItem] = []

    for module_name in required_python_modules:
        if module_is_available(module_name):
            items.append(
                DependencyItem(
                    category="python",
                    name=module_name,
                    status="ok",
                    detail="available",
                )
            )
        else:
            items.append(
                DependencyItem(
                    category="python",
                    name=module_name,
                    status="missing",
                    detail=f"Python module '{module_name}' is not installed",
                    remediation="Run the installer or pip install the project requirements",
                )
            )

    for binary_name in required_system_binaries:
        path = binary_path(binary_name)
        if path:
            items.append(
                DependencyItem(
                    category="system",
                    name=binary_name,
                    status="ok",
                    detail=path,
                )
            )
        else:
            items.append(
                DependencyItem(
                    category="system",
                    name=binary_name,
                    status="missing",
                    detail=f"Missing system binary: {binary_name}",
                    remediation="Run the installer to fetch the system toolchain",
                )
            )

    probe = inventory_probe or probe_ollama_inventory
    ollama_available, installed_models, ollama_detail = probe(ollama_bin, ollama_host)
    installed_models = [model for model in installed_models if model]

    items.append(
        DependencyItem(
            category="ollama",
            name="server",
            status="ok" if ollama_available else "missing",
            detail=ollama_detail or "available",
            remediation=None if ollama_available else "Install and start Ollama",
        )
    )

    installed_set = {model for model in installed_models}
    for required_name in required_models:
        is_present = any(model_matches(installed_name, required_name) for installed_name in installed_set)
        if is_present and ollama_available:
            items.append(
                DependencyItem(
                    category="model",
                    name=required_name,
                    status="ok",
                    detail="installed",
                )
            )
        else:
            detail = "Ollama server unavailable" if not ollama_available else "model not installed"
            items.append(
                DependencyItem(
                    category="model",
                    name=required_name,
                    status="missing",
                    detail=detail,
                    remediation="Run the installer to build the local Ollama models",
                )
            )

    if ollama_available:
        items.append(
            DependencyItem(
                category="ollama",
                name="inventory",
                status="ok",
                detail=f"{len(installed_models)} model(s) available",
            )
        )

    from datetime import datetime, timezone

    return DependencyReport(
        checked_at=datetime.now(timezone.utc).isoformat(),
        items=items,
        installed_models=installed_models,
        ollama_available=ollama_available,
        ollama_detail=ollama_detail,
    )
