"""Render the widget with example trackers to docs/cards.png and docs/donuts.png.

Uses made-up trackers, never your own data/trackers.json.
    python tools/make_screenshot.py [output_dir]
Set QT_SCALE_FACTOR=2 for high-DPI images.
"""
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

app_dir = Path(__file__).resolve().parent.parent
out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else app_dir / "docs"
out_dir.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(app_dir))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

from pies import config as cfg_mod
from pies import model, theme
from pies.store import Store
from pies.widget import PiesWindow

t = date.today()
d = lambda n: (t + timedelta(days=n)).isoformat()
P = model.PALETTE


def tracker(kind, color, **fields):
    tr = model.default_tracker(kind, t, color)
    tr.update(fields)
    return tr


demo = [
    tracker("countdown", P[0], name="Lisbon trip", start=d(-21), target=d(23)),
    tracker("counter", P[2], name="Reading", current=212, total=384, unit="pages", step=1,
            started=d(-16), log=[[d(-16), 0], [d(0), 212]]),
    tracker("counter", P[1], name="Running", current=86, total=200, unit="km", step=1,
            started=d(-30), deadline=d(45), log=[[d(-30), 0], [d(0), 86]]),
    tracker("period", P[3], name="", period="year"),
    tracker("period", P[4 % len(P)], name="", period="month"),
]

app = QApplication([])
theme.apply(app)


def render(name, **overrides):
    path = Path(tempfile.mkdtemp()) / "trackers.json"
    path.write_text(json.dumps({"version": 1, "trackers": demo}), encoding="utf-8")
    cfg = json.loads(json.dumps(cfg_mod.DEFAULTS))
    cfg.update({"data_path": str(path), "dock": "none", "opacity": 1.0,
                "position": {"x": 40, "y": 40}}, **overrides)
    win = PiesWindow(cfg, Store(path, seed=False))
    win.show()
    app.processEvents()
    img = win.grab().toImage()
    dpr = img.devicePixelRatio()
    img.setDevicePixelRatio(1)
    pad = int(28 * dpr)
    bg = QImage(img.width() + 2 * pad, img.height() + 2 * pad, QImage.Format_ARGB32)
    p = QPainter(bg)
    g = QLinearGradient(0, 0, bg.width(), bg.height())
    g.setColorAt(0, QColor("#1f3b57"))
    g.setColorAt(1, QColor("#3a2448"))
    p.fillRect(bg.rect(), g)
    p.drawImage(QPoint(pad, pad), img)
    p.end()
    bg.save(str(out_dir / name))
    print(out_dir / name, bg.width(), bg.height())
    win.hide()


render("cards.png")
render("donuts.png", layout="pies", chart="donut", orientation="horizontal")
