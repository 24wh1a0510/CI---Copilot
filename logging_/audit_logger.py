"""Structured, append-only audit trail for every tool call, agent decision, retry,
and failure in a run. One JSONL file per run so the UI can tail it live."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

AUDIT_DIR = Path(__file__).resolve().parent.parent / "data" / "audit_logs"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)


class AuditLogger:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.path = AUDIT_DIR / f"{run_id}.jsonl"
        self._events: list[dict[str, Any]] = []

    def log(self, event_type: str, agent: str, message: str, **extra: Any) -> dict[str, Any]:
        event = {
            "timestamp": datetime.utcnow().isoformat(),
            "run_id": self.run_id,
            "event_type": event_type,  # tool_call | agent_output | decision | retry | failure | limit_reached
            "agent": agent,
            "message": message,
            **extra,
        }
        self._events.append(event)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        return event

    def tool_call(self, agent: str, tool: str, args: dict, ok: bool, note: str = ""):
        return self.log("tool_call", agent, f"{tool} -> {'ok' if ok else 'failed'} {note}", tool=tool, args=args, ok=ok)

    def retry(self, agent: str, reason: str, attempt: int):
        return self.log("retry", agent, reason, attempt=attempt)

    def failure(self, agent: str, reason: str):
        return self.log("failure", agent, reason)

    def decision(self, agent: str, decision: str):
        return self.log("decision", agent, decision)

    def limit_reached(self, agent: str, which: str):
        return self.log("limit_reached", agent, f"Execution limit reached: {which}")

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @classmethod
    def load(cls, run_id: str) -> list[dict[str, Any]]:
        path = AUDIT_DIR / f"{run_id}.jsonl"
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
