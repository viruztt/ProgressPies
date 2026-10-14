"""The tracker list on disk: data/trackers.json.

Written atomically (temp file + os.replace) with one rolling .bak, the same
way Mouse Odometer stores its counters. The file is meant to be readable and
hand-editable: the widget notices when it changes on disk and reloads.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from . import model

VERSION = 1


class Store:
    def __init__(self, path: str | os.PathLike, seed: bool = True):
        self.path = Path(path)
        self.trackers: list[dict] = []
        self._mtime = 0.0
        self.created_fresh = False
        if not self.load() and seed:
            self.trackers = model.sample_trackers()
            self.created_fresh = True
            self.save()

    # ------------------------------------------------------------------ #
    def load(self) -> bool:
        for candidate in (self.path, self.path.with_suffix(".json.bak")):
            if not candidate.exists():
                continue
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                continue
            items = raw.get("trackers") if isinstance(raw, dict) else raw
            if not isinstance(items, list):
                continue
            today = date.today()
            out, seen = [], set()
            for t in items:
                if not isinstance(t, dict):
                    continue
                t = model.normalize(t, today)
                while t["id"] in seen:
                    t["id"] = model.new_id()
                seen.add(t["id"])
                out.append(t)
            self.trackers = out
            self._mtime = self._disk_mtime()
            return True
        return False

    def save(self) -> bool:
        payload = json.dumps({"version": VERSION, "trackers": self.trackers},
                             indent=2, ensure_ascii=False)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                try:
                    os.replace(self.path, self.path.with_suffix(".json.bak"))
                except Exception:
                    pass
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self.path)
            self._mtime = self._disk_mtime()
            return True
        except Exception:
            return False

    def _disk_mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    def changed_on_disk(self) -> bool:
        m = self._disk_mtime()
        return bool(m) and m != self._mtime

    # ------------------------------------------------------------------ #
    def get(self, tid: str) -> dict | None:
        for t in self.trackers:
            if t["id"] == tid:
                return t
        return None

    def find(self, name_or_id: str) -> dict | None:
        """Exact id, then case-insensitive name, then unique name prefix."""
        key = name_or_id.strip().lower()
        for t in self.trackers:
            if t["id"].lower() == key:
                return t
        named = [t for t in self.trackers if t.get("name", "").lower() == key]
        if named:
            return named[0]
        pref = [t for t in self.trackers
                if t.get("name", "").lower().startswith(key)]
        return pref[0] if len(pref) == 1 else None

    def remove(self, tid: str) -> None:
        self.trackers = [t for t in self.trackers if t["id"] != tid]

    def replace_all(self, trackers: list[dict]) -> None:
        today = date.today()
        self.trackers = [model.normalize(t, today) for t in trackers]
