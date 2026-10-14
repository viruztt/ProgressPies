"""Appearance settings — a plain JSON file next to the app.

The trackers themselves live in data/trackers.json (see store.py).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_DATA_PATH = APP_DIR / "data" / "trackers.json"

DOCKS = ("right", "left", "none")
VALIGNS = ("top", "center", "bottom")

DEFAULTS = {
    "dock": "right",          # "right" | "left" | "none" (free floating)
    "valign": "center",       # where a docked widget sits until you drag it
    "margin": 12,             # gap to the screen edge when docked
    "layout": "cards",        # "cards" (pie + text) | "pies" (pies only)
    "chart": "pie",           # "pie" | "donut"
    "orientation": "vertical",  # "vertical" | "horizontal"
    "font_size": 10,
    "opacity": 0.93,
    "window_layer": "normal",  # "top" | "normal" | "bottom"
    "click_through": False,
    "hide_completed": False,
    "wheel_adjust": True,     # scroll over a counter's pie to change it
    "refresh": 30.0,          # seconds between re-evaluations
    "data_path": "",
    "position": {"x": None, "y": None},
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
        except Exception:
            pass
    if cfg["dock"] not in DOCKS:
        cfg["dock"] = "right"
    if cfg["valign"] not in VALIGNS:
        cfg["valign"] = "center"
    if cfg["layout"] not in ("cards", "pies"):
        cfg["layout"] = "cards"
    if cfg["chart"] not in ("pie", "donut"):
        cfg["chart"] = "pie"
    if cfg["orientation"] not in ("vertical", "horizontal"):
        cfg["orientation"] = "vertical"
    if cfg["window_layer"] not in ("top", "normal", "bottom"):
        cfg["window_layer"] = "normal"
    if not isinstance(cfg.get("position"), dict):
        cfg["position"] = {"x": None, "y": None}
    return cfg


def save(cfg: dict) -> None:
    try:
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        pass


def data_path(cfg: dict) -> Path:
    p = (cfg.get("data_path") or "").strip()
    return Path(p) if p else DEFAULT_DATA_PATH
