from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def format_sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


@dataclass
class SSEEventFormatter:
    seq: int = 0

    def metadata(self, data: dict[str, Any]) -> str:
        return format_sse_event("metadata", data)

    def delta(self, text: str) -> str:
        self.seq += 1
        return format_sse_event("delta", {"seq": self.seq, "text": text})

    def error(self, code: str, message: str) -> str:
        return format_sse_event("error", {"code": code, "message": message})

    def done(self, *, status: str = "ok") -> str:
        return format_sse_event("done", {"status": status})
