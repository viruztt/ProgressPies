"""The floating, edge-docked column of pies."""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QGuiApplication, QIcon, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QSystemTrayIcon, QWidget,
)

from . import config as cfg_mod
from . import model
from .card import BG, MUTED, PieCard, paint_pie

SNAP_PX = 40          # release this close to an edge and the widget docks to it
MAX_TEXT_W = 300
MIN_TEXT_W = 150


class PiesWindow(QWidget):
    def __init__(self, cfg: dict, store):
        super().__init__()
        self.cfg = cfg
        self.store = store
        self.cards: dict[str, PieCard] = {}
        self._drag_offset: QPoint | None = None
        self._dragged = False
        self._text_w = 0
        self._editor = None

        self.setWindowTitle("Progress Pies")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.Tool, True)
        self._apply_flags()
        self.setWindowOpacity(float(cfg.get("opacity", 0.93)))

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(7, 7, 7, 7)
        self.grid.setSpacing(6)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        self._tray()
        self.build()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(int(max(1.0, float(cfg.get("refresh", 30.0))) * 1000))

        # Pick up hand edits to trackers.json and `main.py --add/--set`.
        self.watch = QTimer(self)
        self.watch.timeout.connect(self._check_disk)
        self.watch.start(2000)

        screens = QGuiApplication.instance()
        screens.screenAdded.connect(lambda *_: QTimer.singleShot(500, self.place))
        screens.screenRemoved.connect(lambda *_: QTimer.singleShot(500, self.place))

    # ------------------------------------------------------------------ #
    # building
    # ------------------------------------------------------------------ #
    def _shown_trackers(self) -> list[tuple[dict, model.Status]]:
        out = []
        for t in self.store.trackers:
            if not t.get("visible", True):
                continue
            st = model.evaluate(t)
            if self.cfg.get("hide_completed") and st.done:
                continue
            out.append((t, st))
        return out

    def build(self) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.cards.clear()

        shown = self._shown_trackers()
        if not shown:
            hint = QLabel("No trackers yet.\nRight-click → Add tracker")
            hint.setStyleSheet(f"color: {MUTED.name()}; padding: 10px 14px;")
            hint.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(hint, 0, 0)
            hint.show()
            self._text_w = 0
            self.adjustSize()
            self.place()
            return

        for t, st in shown:
            card = PieCard(t, self.cfg, self)
            card.set_status(st, model.display_name(t))
            card.edit_requested.connect(self.edit_tracker)
            card.adjust_requested.connect(self.adjust_counter)
            self.cards[t["id"]] = card

        self._text_w = self._common_text_width()
        for c in self.cards.values():
            c.apply_size(self._text_w)
        self._arrange()
        self.place()

    def _common_text_width(self) -> int:
        cards = list(self.cards.values())
        if not cards:
            return 0
        natural = max(c.natural_text_width() for c in cards)
        if self.cfg.get("layout") == "pies":
            d = cards[0].pie_size()
            return max(d, min(natural, int(d * 1.7)))
        return max(MIN_TEXT_W, min(natural, MAX_TEXT_W))

    def _arrange(self) -> None:
        cards = list(self.cards.values())
        for c in cards:
            self.grid.removeWidget(c)
        if not cards:
            return
        g = self._screen().availableGeometry()
        m = self.grid.contentsMargins()
        sp = self.grid.spacing()
        cw, ch = cards[0].width(), cards[0].height()
        if self.cfg.get("orientation") == "horizontal":
            per = max(1, (g.width() - 2 * int(self.cfg.get("margin", 12))
                          - m.left() - m.right() + sp) // (cw + sp))
            for i, c in enumerate(cards):
                self.grid.addWidget(c, i // per, i % per)
        else:
            per = max(1, (g.height() - 2 * int(self.cfg.get("margin", 12))
                          - m.top() - m.bottom() + sp) // (ch + sp))
            cols = (len(cards) + per - 1) // per
            for i, c in enumerate(cards):
                col = i // per
                # Docked right: first column hugs the edge, extras grow inward.
                if self.cfg.get("dock") == "right":
                    col = cols - 1 - col
                self.grid.addWidget(c, i % per, col)
        # Children added to a visible window are only shown on the next event
        # loop pass; show them now so adjustSize() counts them.
        for c in cards:
            c.show()
        self.grid.activate()
        self.adjustSize()

    def refresh(self) -> None:
        shown = self._shown_trackers()
        if [t["id"] for t, _ in shown] != list(self.cards):
            self.build()  # something completed / was hidden
            return
        for t, st in shown:
            self.cards[t["id"]].set_status(st, model.display_name(t))
        w = self._common_text_width()
        if w != self._text_w:
            self._text_w = w
            for c in self.cards.values():
                c.apply_size(w)
            self._arrange()
            self.place()

    def _check_disk(self) -> None:
        if self.store.changed_on_disk() and self.store.load():
            self.build()

    def _commit(self) -> None:
        self.store.save()
        self.refresh()

    # ------------------------------------------------------------------ #
    # placement
    # ------------------------------------------------------------------ #
    def _screen(self):
        pos = self.cfg.get("position") or {}
        if pos.get("x") is not None and pos.get("y") is not None:
            s = QGuiApplication.screenAt(QPoint(int(pos["x"]) + 5, int(pos["y"]) + 5))
            if s is not None:
                return s
        return QGuiApplication.primaryScreen()

    def place(self) -> None:
        """Put the window where the config says: hugging an edge, or free."""
        self.adjustSize()
        g = self._screen().availableGeometry()
        margin = int(self.cfg.get("margin", 12))
        pos = self.cfg.get("position") or {}
        dock = self.cfg.get("dock", "right")
        w, h = self.width(), self.height()

        if pos.get("y") is not None:
            y = int(pos["y"])
        else:
            va = self.cfg.get("valign", "center")
            y = (g.top() + margin if va == "top" else
                 g.bottom() - h - margin + 1 if va == "bottom" else
                 g.top() + (g.height() - h) // 2)

        if dock == "right":
            x = g.right() - w - margin + 1
        elif dock == "left":
            x = g.left() + margin
        elif pos.get("x") is not None:
            x = int(pos["x"])
        else:
            x = g.right() - w - margin + 1

        x = max(g.left(), min(x, g.right() - w + 1))
        y = max(g.top(), min(y, g.bottom() - h + 1))
        self.move(x, y)

    def _save_position(self) -> None:
        self.cfg["position"] = {"x": self.x(), "y": self.y()}
        cfg_mod.save(self.cfg)

    # ------------------------------------------------------------------ #
    # painting / dragging
    # ------------------------------------------------------------------ #
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, BG)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        p.drawPath(path)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragged = False
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and e.buttons() & Qt.LeftButton:
            target = e.globalPosition().toPoint() - self._drag_offset
            if not self._dragged and (target - self.pos()).manhattanLength() < 4:
                return
            self._dragged = True
            self.move(target)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag_offset is None:
            return
        self._drag_offset = None
        if not self._dragged:
            return
        scr = QGuiApplication.screenAt(self.frameGeometry().center()) or self._screen()
        g = scr.availableGeometry()
        fg = self.frameGeometry()
        if abs(fg.right() - g.right()) <= SNAP_PX:
            self.cfg["dock"] = "right"
        elif abs(fg.left() - g.left()) <= SNAP_PX:
            self.cfg["dock"] = "left"
        else:
            self.cfg["dock"] = "none"
        self._save_position()
        self._arrange()
        self.place()
        self._save_position()

    # ------------------------------------------------------------------ #
    # tracker actions
    # ------------------------------------------------------------------ #
    def adjust_counter(self, tid: str, delta: float) -> None:
        t = self.store.get(tid)
        if t and t.get("type") == "counter":
            model.bump_counter(t, delta)
            self._commit()

    def set_counter_value(self, tid: str) -> None:
        t = self.store.get(tid)
        if not t:
            return
        unit = t.get("unit") or "value"
        decimals = 0 if all(float(x).is_integer() for x in
                            (t.get("current", 0), t.get("step", 1))) else 2
        v, ok = QInputDialog.getDouble(
            self, model.display_name(t),
            f"Current {unit} (of {model.fmt_num(t.get('total'))}):",
            float(t.get("current", 0)), 0, 1e12, decimals)
        if ok:
            model.set_counter(t, v)
            self._commit()

    def delete_tracker(self, tid: str) -> None:
        t = self.store.get(tid)
        if not t:
            return
        if QMessageBox.question(
                self, "Delete tracker",
                f"Delete “{model.display_name(t)}”? This cannot be undone.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.store.remove(tid)
            self.store.save()
            self.build()

    def hide_tracker(self, tid: str) -> None:
        t = self.store.get(tid)
        if t:
            t["visible"] = False
            self.store.save()
            self.build()

    def edit_tracker(self, tid: str | None = None, new_kind: str | None = None) -> None:
        from .editor import EditorDialog
        if self._editor is not None:
            self._editor.raise_()
            self._editor.activateWindow()
            return
        dlg = EditorDialog(self.store.trackers, self.cfg, select=tid,
                           new_kind=new_kind)
        self._editor = dlg
        self.timer.stop()
        self.watch.stop()
        try:
            if dlg.exec():
                self.store.replace_all(dlg.result_trackers())
                self.store.save()
            self.build()
        finally:
            self._editor = None
            self.timer.start()
            self.watch.start()

    # ------------------------------------------------------------------ #
    # menu
    # ------------------------------------------------------------------ #
    def _card_at(self, pos) -> PieCard | None:
        w = self.childAt(pos)
        while w is not None and not isinstance(w, PieCard):
            w = w.parentWidget()
        return w

    def _menu(self, pos):
        m = QMenu(self)
        card = self._card_at(pos)
        if card is not None:
            t = card.tracker
            m.addSection(model.display_name(t))
            if t.get("type") == "counter":
                step = float(t.get("step", 1) or 1)
                s = model.fmt_num(step)
                m.addAction(f"+{s}", lambda tid=t["id"], d=step: self.adjust_counter(tid, d))
                m.addAction(f"−{s}", lambda tid=t["id"], d=step: self.adjust_counter(tid, -d))
                m.addAction("Set value…", lambda tid=t["id"]: self.set_counter_value(tid))
            m.addAction("Edit…", lambda tid=t["id"]: self.edit_tracker(tid))
            m.addAction("Hide from widget", lambda tid=t["id"]: self.hide_tracker(tid))
            m.addAction("Delete…", lambda tid=t["id"]: self.delete_tracker(tid))
            m.addSeparator()

        add = m.addMenu("Add tracker")
        for kind in model.TYPES:
            add.addAction(model.TYPE_LABELS[kind] + "…",
                          lambda k=kind: self.edit_tracker(new_kind=k))
        m.addAction("Edit trackers…", self.edit_tracker)
        m.addSeparator()

        self._radio(m.addMenu("Dock"), "dock",
                    (("right", "Right edge"), ("left", "Left edge"),
                     ("none", "Floating (drag anywhere)")), self._set_dock)
        self._radio(m.addMenu("Vertical position"), "valign",
                    (("top", "Top"), ("center", "Middle"), ("bottom", "Bottom")),
                    self._set_valign, checked=self.cfg.get("position", {}).get("y") is None)
        self._radio(m.addMenu("Layout"), "layout",
                    (("cards", "Pie + text"), ("pies", "Pies only")), self._set_key)
        self._radio(m.addMenu("Chart"), "chart",
                    (("pie", "Pie"), ("donut", "Donut")), self._set_key)
        self._radio(m.addMenu("Orientation"), "orientation",
                    (("vertical", "Vertical column"), ("horizontal", "Horizontal row")),
                    self._set_key)

        a = m.addAction("Hide completed")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("hide_completed")))
        a.toggled.connect(lambda on: self._set_key("hide_completed", bool(on)))

        a = m.addAction("Scroll wheel changes counters")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("wheel_adjust", True)))
        a.toggled.connect(lambda on: self._set_key("wheel_adjust", bool(on)))

        self._radio(m.addMenu("Window layer"), "window_layer",
                    (("top", "Always on top"), ("normal", "Normal (can be covered)"),
                     ("bottom", "Always at the bottom")), self._set_layer)

        a = m.addAction("Click-through")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("click_through", False)))
        a.toggled.connect(self._set_click_through)

        om = m.addMenu("Opacity")
        grp = QActionGroup(om)
        for v in (1.0, 0.93, 0.8, 0.65, 0.5):
            act = QAction(f"{int(v * 100)}%", om)
            act.setCheckable(True)
            act.setChecked(abs(float(self.cfg.get("opacity", 0.93)) - v) < 0.01)
            act.triggered.connect(lambda _c, val=v: self._set_opacity(val))
            grp.addAction(act)
            om.addAction(act)

        sm = m.addMenu("Text size")
        grp = QActionGroup(sm)
        for v in (8, 9, 10, 11, 12, 14):
            act = QAction(f"{v} pt", sm)
            act.setCheckable(True)
            act.setChecked(int(self.cfg.get("font_size", 10)) == v)
            act.triggered.connect(lambda _c, val=v: self._set_key("font_size", val))
            grp.addAction(act)
            sm.addAction(act)

        m.addSeparator()
        m.addAction("Open data file", self._open_data)
        m.addAction("Reset position", self._reset_position)
        m.addAction("Quit", self.quit)
        m.exec(self.mapToGlobal(pos))

    def _radio(self, menu, key, options, handler, checked=True):
        grp = QActionGroup(menu)
        for value, text in options:
            act = QAction(text, menu)
            act.setCheckable(True)
            act.setChecked(checked and self.cfg.get(key) == value)
            act.triggered.connect(lambda _c, v=value, k=key: handler(k, v))
            grp.addAction(act)
            menu.addAction(act)

    # ------------------------------------------------------------------ #
    # settings
    # ------------------------------------------------------------------ #
    def _set_key(self, key, value):
        self.cfg[key] = value
        cfg_mod.save(self.cfg)
        self.build()

    def _set_dock(self, _key, value):
        self.cfg["dock"] = value
        if value == "none":
            self.cfg["position"] = {"x": self.x(), "y": self.y()}
        cfg_mod.save(self.cfg)
        self.build()
        self._save_position()

    def _set_valign(self, _key, value):
        self.cfg["valign"] = value
        self.cfg["position"] = {"x": self.x(), "y": None}
        if self.cfg.get("dock") == "none":
            self.cfg["dock"] = "right"
        cfg_mod.save(self.cfg)
        self.place()

    def _apply_flags(self):
        layer = self.cfg.get("window_layer", "normal")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, layer == "top")
        self.setWindowFlag(Qt.WindowStaysOnBottomHint, layer == "bottom")
        self.setWindowFlag(Qt.WindowTransparentForInput,
                           bool(self.cfg.get("click_through", False)))

    def _set_layer(self, _key, value):
        self.cfg["window_layer"] = value
        cfg_mod.save(self.cfg)
        self._apply_flags()
        self.show()

    def _set_click_through(self, on):
        self.cfg["click_through"] = bool(on)
        cfg_mod.save(self.cfg)
        self._apply_flags()
        self.show()
        if hasattr(self, "_ct_action"):
            self._ct_action.setChecked(bool(on))

    def _set_opacity(self, v):
        self.cfg["opacity"] = v
        self.setWindowOpacity(v)
        cfg_mod.save(self.cfg)

    def _reset_position(self):
        self.cfg["dock"] = "right"
        self.cfg["valign"] = "center"
        self.cfg["position"] = {"x": None, "y": None}
        cfg_mod.save(self.cfg)
        self.build()
        self.show()

    def _open_data(self):
        path = str(self.store.path)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # tray
    # ------------------------------------------------------------------ #
    def _tray(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        paint_pie(p, QRectF(4, 4, 56, 56), 0.68, QColor("#3FC1E0"), "pie")
        p.end()

        self.tray = QSystemTrayIcon(QIcon(pm), self)
        self.tray.setToolTip("Progress Pies")
        menu = QMenu()
        menu.addAction("Edit trackers…", self.edit_tracker)
        menu.addAction("Bring to front", self._bring_to_front)
        menu.addAction("Show / hide", self._toggle_visible)
        self._ct_action = menu.addAction("Click-through")
        self._ct_action.setCheckable(True)
        self._ct_action.setChecked(bool(self.cfg.get("click_through", False)))
        self._ct_action.toggled.connect(
            lambda on: on != bool(self.cfg.get("click_through")) and self._set_click_through(on))
        menu.addAction("Reset position", self._reset_position)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._toggle_visible()
            if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self.setWindowIcon(QIcon(pm))

    def _toggle_visible(self):
        self.setVisible(not self.isVisible())

    def _bring_to_front(self):
        """The widget has no taskbar button, so this is how you get it back."""
        self.show()
        self.raise_()
        self.activateWindow()

    def quit(self):
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, e):
        self.quit()
        e.accept()
