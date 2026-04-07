"""Small structured logging helpers for runtime services."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def emit_runtime_event(service: str, event: str, **fields: Any) -> str:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": service,
        "event": event,
        **fields,
    }
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    print(line)
    return line
