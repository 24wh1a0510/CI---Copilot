"""Reusable Watchlists — save/load named competitor sets.

Storage: data/watchlists.json  (dict keyed by watchlist name)
Every entry is a list of {"name": str, "domain": str} competitor records.

API (all functions are synchronous, UI-friendly):
    save_watchlist(name, competitors)  -> None
    load_watchlist(name)               -> list[dict] | None
    list_watchlists()                  -> list[str]
    delete_watchlist(name)             -> bool
    rename_watchlist(old, new)         -> bool
"""
from __future__ import annotations

import json
from pathlib import Path

_WATCHLIST_FILE = Path(__file__).resolve().parent.parent / "data" / "watchlists.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_all() -> dict[str, list[dict]]:
    if not _WATCHLIST_FILE.exists():
        return {}
    try:
        data = json.loads(_WATCHLIST_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _save_all(data: dict[str, list[dict]]) -> None:
    _WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    _WATCHLIST_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_watchlist(name: str, competitors: list[dict]) -> None:
    """Persist (or overwrite) a watchlist by name.

    Each competitor is a dict with at minimum {"name": str} and optionally
    {"domain": str}.  Unknown keys are preserved transparently.
    """
    if not name or not name.strip():
        raise ValueError("Watchlist name must not be empty.")
    data = _load_all()
    data[name.strip()] = [dict(c) for c in competitors]
    _save_all(data)


def load_watchlist(name: str) -> list[dict] | None:
    """Return the competitor list for *name*, or None if it doesn't exist."""
    data = _load_all()
    return data.get(name.strip()) if name else None


def list_watchlists() -> list[str]:
    """Return a sorted list of saved watchlist names."""
    data = _load_all()
    return sorted(data.keys())


def delete_watchlist(name: str) -> bool:
    """Remove a watchlist.  Returns True if it existed, False otherwise."""
    data = _load_all()
    if name not in data:
        return False
    del data[name]
    _save_all(data)
    return True


def rename_watchlist(old_name: str, new_name: str) -> bool:
    """Rename a watchlist.  Returns True on success, False if old_name not found
    or new_name already exists."""
    if not old_name or not new_name or old_name == new_name:
        return False
    data = _load_all()
    if old_name not in data or new_name in data:
        return False
    data[new_name] = data.pop(old_name)
    _save_all(data)
    return True
