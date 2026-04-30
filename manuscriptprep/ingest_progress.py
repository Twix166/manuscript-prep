"""Structured ingest progress snapshots for the gateway and web UI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class IngestProgressTracker:
    path: Optional[Path]
    state: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.state.setdefault("pipeline", "ingest")
        self.state.setdefault("available", True)
        self.state.setdefault("status", "running")
        self.state.setdefault("message", "Starting ingest.")
        self.state.setdefault("current_stage", None)
        self.state.setdefault("current_step", None)
        self.state.setdefault("overall_percent", 0.0)
        self.state.setdefault("stage_percent", 0.0)
        self.state.setdefault("recent_events", [])
        self.state.setdefault("warnings", [])
        self.state.setdefault("updated_at", utc_now_iso())
        self._write()

    def update(
        self,
        *,
        message: Optional[str] = None,
        current_stage: Optional[str] = None,
        current_step: Optional[str] = None,
        overall_percent: Optional[float] = None,
        stage_percent: Optional[float] = None,
        status: Optional[str] = None,
        **fields: Any,
    ) -> None:
        if message is not None:
            self.state["message"] = message
        if current_stage is not None:
            self.state["current_stage"] = current_stage
        if current_step is not None:
            self.state["current_step"] = current_step
        if overall_percent is not None:
            self.state["overall_percent"] = round(float(overall_percent), 1)
        if stage_percent is not None:
            self.state["stage_percent"] = round(float(stage_percent), 1)
        if status is not None:
            self.state["status"] = status
        for key, value in fields.items():
            if value is not None:
                self.state[key] = value
        self.state["updated_at"] = utc_now_iso()
        self._write()

    def event(self, event_type: str, **fields: Any) -> None:
        event = {"timestamp": utc_now_iso(), "event_type": event_type}
        event.update({key: value for key, value in fields.items() if value is not None})
        recent = self.state.setdefault("recent_events", [])
        recent.append(event)
        if len(recent) > 25:
            self.state["recent_events"] = recent[-25:]
        self.state["last_event_type"] = event_type
        self.state["updated_at"] = event["timestamp"]
        for key, value in fields.items():
            if value is not None:
                self.state[key] = value
        self._write()

    def warn(self, message: str) -> None:
        warnings = self.state.setdefault("warnings", [])
        warnings.append(message)
        self.state["updated_at"] = utc_now_iso()
        self._write()

    def finish(self, *, status: str = "succeeded", message: str = "Ingest complete.", **fields: Any) -> None:
        self.update(status=status, message=message, overall_percent=100.0, stage_percent=100.0, **fields)

    def _write(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.state, indent=2, ensure_ascii=False) + "\n"
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self.path)


def load_ingest_progress(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
