#!/usr/bin/env python3
"""Install and verify the ManuscriptPrep runtime stack."""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = REPO_ROOT / "work" / "installer"


def add_repo_root_to_path() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


add_repo_root_to_path()

from manuscriptprep.dependencies import (  # noqa: E402
    DEFAULT_OLLAMA_BASE_MODEL,
    check_dependencies,
    model_matches,
    probe_ollama_inventory,
)


MODEL_BUILD_FILES: dict[str, Path] = {
    "manuscriptprep-structure": REPO_ROOT / "modelfiles" / "Modelfile.structure",
    "manuscriptprep-dialogue": REPO_ROOT / "modelfiles" / "Modelfile.dialogue",
    "manuscriptprep-entities": REPO_ROOT / "modelfiles" / "Modelfile.entity",
    "manuscriptprep-dossiers": REPO_ROOT / "modelfiles" / "Modelfile.dossier",
    "manuscriptprep-resolver": REPO_ROOT / "modelfiles" / "Modelfile.resolver",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install and verify the ManuscriptPrep runtime stack.")
    parser.add_argument("--check-only", action="store_true", help="Only report missing dependencies.")
    return parser.parse_args()


def run_command(cmd: list[str], *, cwd: Path | None = None, input_text: str | None = None) -> None:
    print(f"[install] $ {' '.join(shlex.quote(part) for part in cmd)}")
    subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        input=input_text,
        text=True,
        check=True,
    )


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def install_python_requirements() -> None:
    requirements = REPO_ROOT / "requirements.txt"
    if not requirements.is_file():
        raise RuntimeError(f"requirements.txt not found at {requirements}")
    run_command([sys.executable, "-m", "pip", "install", "-r", str(requirements)])


def install_with_brew(packages: list[str]) -> bool:
    brew = shutil.which("brew")
    if not brew:
        return False
    run_command([brew, "install", *packages])
    return True


def install_with_apt(packages: list[str]) -> bool:
    apt_get = shutil.which("apt-get")
    if not apt_get:
        return False

    prefix: list[str] = []
    if os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            raise RuntimeError("apt-get is available but sudo is not. Run this installer as root or install sudo.")
        prefix = [sudo]

    run_command(prefix + [apt_get, "update"])
    run_command(prefix + [apt_get, "install", "-y", *packages])
    return True


def install_ollama_official_script() -> None:
    from urllib import request as urllib_request

    print("[install] Downloading Ollama install script")
    payload = urllib_request.urlopen("https://ollama.com/install.sh", timeout=60).read().decode("utf-8")
    run_command(["sh"], input_text=payload)


def install_ollama() -> None:
    system = platform.system().lower()
    if system == "darwin":
        if install_with_brew(["ollama"]):
            return
        install_ollama_official_script()
        return

    if system == "linux":
        if command_exists("brew") and install_with_brew(["ollama"]):
            return
        install_ollama_official_script()
        return

    if system == "windows":
        winget = shutil.which("winget")
        if winget:
            run_command([winget, "install", "--id", "Ollama.Ollama", "-e"])
            return
        raise RuntimeError("Windows detected but winget is not available.")

    raise RuntimeError(f"Unsupported platform for Ollama installation: {platform.system()}")


def ensure_system_packages() -> None:
    system = platform.system().lower()
    if system == "darwin":
        install_with_brew(["poppler", "ocrmypdf", "tesseract", "ghostscript"])
        return
    if system == "linux":
        if install_with_brew(["poppler", "ocrmypdf", "tesseract", "ghostscript"]):
            return
        if not install_with_apt(["poppler-utils", "ocrmypdf", "tesseract-ocr", "ghostscript"]):
            raise RuntimeError("No supported package manager found for Linux system dependencies.")
        return
    if system == "windows":
        print("[install] System packages on Windows are handled by the Ollama installer and user-level tooling.")
        return
    raise RuntimeError(f"Unsupported platform: {platform.system()}")


def ollama_model_present(ollama_bin: str, model_name: str) -> bool:
    available, installed_models, _ = probe_ollama_inventory(ollama_bin, None)
    if not available:
        return False
    return any(model_matches(installed, model_name) for installed in installed_models)


def wait_for_ollama(ollama_bin: str, timeout_s: int = 30) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        available, _, _ = probe_ollama_inventory(ollama_bin, None)
        if available:
            return True
        time.sleep(1.0)
    return False


def ensure_ollama_server(ollama_bin: str) -> None:
    if probe_ollama_inventory(ollama_bin, None)[0]:
        return

    print("[install] Starting ollama serve in the background")
    log_dir = WORK_ROOT
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "ollama-serve.log"
    with log_path.open("a", encoding="utf-8") as log_handle:
        subprocess.Popen(
            [ollama_bin, "serve"],
            cwd=str(REPO_ROOT),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )

    if not wait_for_ollama(ollama_bin):
        raise RuntimeError(
            "Unable to reach Ollama after starting the service. Check the logs at "
            f"{log_path}."
        )


def ensure_ollama_base_model(ollama_bin: str) -> None:
    if ollama_model_present(ollama_bin, DEFAULT_OLLAMA_BASE_MODEL):
        return
    run_command([ollama_bin, "pull", DEFAULT_OLLAMA_BASE_MODEL])


def ensure_ollama_models(ollama_bin: str) -> None:
    for model_name, modelfile in MODEL_BUILD_FILES.items():
        if ollama_model_present(ollama_bin, model_name):
            continue
        if not modelfile.is_file():
            raise RuntimeError(f"Missing Modelfile: {modelfile}")
        run_command([ollama_bin, "create", model_name, "-f", str(modelfile)])


def print_report(title: str, report) -> None:
    print(title)
    for item in report.items:
        marker = "OK" if item.status == "ok" else "MISSING"
        print(f"  [{marker}] {item.category}: {item.name} - {item.detail}")
        if item.remediation and item.status != "ok":
            print(f"       {item.remediation}")


def main() -> int:
    args = parse_args()
    ollama_bin = shutil.which("ollama") or "ollama"

    report = check_dependencies(ollama_bin=ollama_bin)
    print_report("[install] Preflight dependency report", report)
    if not report.has_missing:
        print("[install] All dependencies are already satisfied.")
        return 0

    if args.check_only:
        return 1

    try:
        install_python_requirements()
        ensure_system_packages()

        if not command_exists("ollama"):
            install_ollama()
            ollama_bin = shutil.which("ollama") or ollama_bin

        ensure_ollama_server(ollama_bin)
        ensure_ollama_base_model(ollama_bin)
        ensure_ollama_models(ollama_bin)
    except Exception as exc:
        print(f"[install] ERROR: {exc}", file=sys.stderr)
        return 1

    final_report = check_dependencies(ollama_bin=ollama_bin)
    print_report("[install] Final dependency report", final_report)
    if final_report.has_missing:
        print("[install] Some dependencies are still missing.", file=sys.stderr)
        return 1

    print("[install] ManuscriptPrep runtime stack is satisfied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
