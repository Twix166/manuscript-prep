from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT


SAMPLE_MANUSCRIPT_TEXT = """TREASURE ISLAND

CHAPTER I

Jim Hawkins said, "We should go now."

Long John Silver smiled.

CHAPTER II

Jim thought about Silver and the inn.
"""


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def sample_manuscript_text() -> str:
    return SAMPLE_MANUSCRIPT_TEXT


@pytest.fixture
def fake_pdf_tool_dir(tmp_path: Path, sample_manuscript_text: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    pdftotext = f"""#!/usr/bin/env python3
from pathlib import Path
import sys

text = {sample_manuscript_text!r}
out_path = Path(sys.argv[-1])
out_path.write_text(text, encoding="utf-8")
"""
    pdfinfo = """#!/usr/bin/env python3
print("Pages:          3")
"""
    ocrmypdf = """#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys

src = Path(sys.argv[-2])
dst = Path(sys.argv[-1])
shutil.copyfile(src, dst)
"""

    write_executable(bin_dir / "pdftotext", pdftotext)
    write_executable(bin_dir / "pdfinfo", pdfinfo)
    write_executable(bin_dir / "ocrmypdf", ocrmypdf)
    return bin_dir


@pytest.fixture
def fake_ollama_dir(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ollama = """#!/usr/bin/env python3
import json
import sys

model = sys.argv[2]
_ = sys.stdin.read()

payloads = {
    "manuscriptprep-structure": {
        "chapters": ["CHAPTER I", "CHAPTER II"],
        "parts": [],
        "scene_breaks": [],
        "status": "ok",
    },
    "manuscriptprep-dialogue": {
        "pov": "third_person_limited",
        "dialogue": True,
        "internal_thought": True,
        "explicitly_attributed_speakers": ["Jim Hawkins", "Long John Silver"],
        "unattributed_dialogue_present": False,
    },
    "manuscriptprep-entities": {
        "characters": ["Jim", "Jim Hawkins", "Long John Silver", "Silver"],
        "places": ["Admiral Benbow Inn"],
        "objects": ["map"],
        "identity_notes": ["Jim may refer to Jim Hawkins"],
    },
    "manuscriptprep-dossiers": {
        "character_dossiers": [
            {
                "name": "Jim Hawkins",
                "aliases": ["Jim"],
                "role": "protagonist",
                "biography": "Young narrator figure.",
                "personality_traits": ["curious"],
                "vocal_notes": ["clear"],
                "accent": "not specified in excerpt",
                "spoken_dialogue": True,
                "identity_status": "confirmed",
            },
            {
                "name": "Long John Silver",
                "aliases": ["Silver"],
                "role": "antagonist",
                "biography": "Charismatic pirate.",
                "personality_traits": ["charming"],
                "vocal_notes": ["measured"],
                "accent": "not specified in excerpt",
                "spoken_dialogue": True,
                "identity_status": "confirmed",
            },
        ]
    },
    "manuscriptprep-resolver": {
        "canonical_name": "Jim Hawkins",
        "merge": True,
        "confidence": "safe",
        "members_to_merge": ["Jim", "Jim Hawkins"],
        "members_to_keep_separate": [],
        "reasons": ["Common given-name/full-name variant."],
    },
}

print(json.dumps(payloads.get(model, {"status": "ok"})))
"""
    write_executable(bin_dir / "ollama", ollama)
    return bin_dir


@pytest.fixture
def test_env(fake_pdf_tool_dir: Path, fake_ollama_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(fake_pdf_tool_dir), str(fake_ollama_dir), env.get("PATH", "")])
    return env


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n% fake pdf for tests\n")
    return pdf
