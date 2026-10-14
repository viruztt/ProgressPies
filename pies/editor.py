"""Add / edit / reorder trackers, with a live preview of the card."""
from __future__ import annotations

import copy
from datetime import date

from PySide6.QtCore import QDate, QSize, Qt, QTime
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDateEdit,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPushButton, QStackedWidget, QTimeEdit, QVBoxLayout, QWidget,
)

from . import model
from .card import PieCard

SURFACE = "#14151a"
PANEL = "#1a1c24"
INK = "#eef0f5"
INK_MUTED = "#7c8394"

STYLE = f"""
QDialog {{ background: {SURFACE}; }}
QLabel {{ color: {INK}; }}
QLabel#hint {{ color: {INK_MUTED}; }}
QListWidget {{
    background: {PANEL}; color: {INK}; border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px; padding: 4px; outline: none;
}}
QListWidget::item {{ padding: 5px 4px; border-radius: 4px; }}
QListWidget::item:selected {{ background: rgba(63,193,224,0.22); color: {INK}; }}
QLineEdit, QComboBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QPushButton {{
    background: {PANEL}; color: {INK};
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 5px; padding: 4px 8px; min-height: 18px;
}}
QPushButton:hover, QComboBox:hover {{ border-color: rgba(255,255,255,0.3); }}
QPushButton:disabled, QLineEdit:disabled, QDateEdit:disabled,
QTimeEdit:disabled {{ color: {INK_MUTED}; }}
QCheckBox {{ color: {INK}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    width: 0px; border: none;
}}
QPushButton#swatch {{ border-radius: 11px; padding: 0; min-height: 0; }}
"""


def _dot(color: str, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pm)


def _qdate(s: str) -> QDate:
    try:
        d = date.fromisoformat(str(s)[:10])
        return QDate(d.year, d.month, d.day)
    except Exception:
        return QDate.currentDate()


def _iso(qd: QDate) -> str:
    return date(qd.year(), qd.month(), qd.day()).isoformat()


class NumBox(QDoubleSpinBox):
    """Spin box that shows 120 rather than 120.00."""

    def __init__(self, lo=0.0, hi=1e12, parent=None):
        super().__init__(parent)
        self.setRange(lo, hi)
        self.setDecimals(2)
        self.setKeyboardTracking(False)

    def textFromValue(self, v):
        return model.fmt_num(round(v, 2)).replace(",", "")


class EditorDialog(QDialog):
    def __init__(self, trackers: list[dict], cfg: dict, select: str | None = None,
                 new_kind: str | None = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.items = copy.deepcopy(trackers)
        self._loading = False
        self.setWindowTitle("Progress Pies — trackers")
        self.setStyleSheet(STYLE)
        self.resize(780, 540)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        root.setSpacing(14)

        # ---- left: the list ---------------------------------------------- #
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setIconSize(QSize(14, 14))
        self.list.currentRowChanged.connect(self._on_select)
        self.list.model().rowsMoved.connect(self._on_reorder)
        left.addWidget(self.list, 1)
        hint = QLabel("Drag to reorder")
        hint.setObjectName("hint")
        left.addWidget(hint)
        row = QHBoxLayout()
        add = QPushButton("Add")
        am = QMenu(add)
        for kind in model.TYPES:
            am.addAction(model.TYPE_LABELS[kind], lambda k=kind: self._add(k))
        add.setMenu(am)
        row.addWidget(add)
        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.clicked.connect(self._duplicate)
        row.addWidget(self.dup_btn)
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self._delete)
        row.addWidget(self.del_btn)
        left.addLayout(row)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(250)
        root.addWidget(lw)

        # ---- right: the form --------------------------------------------- #
        right = QVBoxLayout()
        right.setSpacing(10)
        self.form_box = QWidget()
        form = QFormLayout(self.form_box)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.name = QLineEdit()
        self.name.textChanged.connect(self._changed)
        form.addRow("Name", self.name)

        self.kind = QComboBox()
        for k in model.TYPES:
            self.kind.addItem(model.TYPE_LABELS[k], k)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        form.addRow("Type", self.kind)

        sw = QHBoxLayout()
        sw.setSpacing(5)
        self.swatches = []
        for c in model.PALETTE:
            b = QPushButton()
            b.setObjectName("swatch")
            b.setFixedSize(22, 22)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, col=c: self._set_color(col))
            self.swatches.append((c, b))
            sw.addWidget(b)
        more = QPushButton("…")
        more.setToolTip("Custom colour")
        more.setFixedWidth(32)
        more.clicked.connect(self._pick_color)
        sw.addWidget(more)
        sw.addStretch(1)
        form.addRow("Colour", sw)

        self.reverse = QComboBox()
        self.reverse.addItem("Progress made (fills up)", False)
        self.reverse.addItem("What's left (empties out)", True)
        self.reverse.currentIndexChanged.connect(self._changed)
        form.addRow("Pie shows", self.reverse)

        self.visible = QCheckBox("Show on the widget")
        self.visible.toggled.connect(self._changed)
        form.addRow("", self.visible)
        right.addWidget(self.form_box)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: rgba(255,255,255,0.1);")
        right.addWidget(line)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._countdown_page())
        self.pages.addWidget(self._counter_page())
        self.pages.addWidget(self._period_page())
        right.addWidget(self.pages)
        right.addStretch(1)

        pv = QHBoxLayout()
        pl = QLabel("Preview")
        pl.setObjectName("hint")
        pv.addWidget(pl, 0, Qt.AlignTop)
        self.preview_host = QHBoxLayout()
        pv.addLayout(self.preview_host)
        pv.addStretch(1)
        right.addLayout(pv)
        self.preview: PieCard | None = None

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Save")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        root.addLayout(right, 1)

        self._fill_list()
        if new_kind:
            self._add(new_kind)
        else:
            idx = next((i for i, t in enumerate(self.items) if t["id"] == select), 0)
            self.list.setCurrentRow(idx if self.items else -1)
        self._sync_enabled()

    # ------------------------------------------------------------------ #
    # type-specific pages
    # ------------------------------------------------------------------ #
    def _countdown_page(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setHorizontalSpacing(12)
        f.setVerticalSpacing(8)
        self.cd_target = QDateEdit()
        self.cd_target.setCalendarPopup(True)
        self.cd_target.setDisplayFormat("ddd d MMM yyyy")
        self.cd_target.dateChanged.connect(self._changed)
        f.addRow("Target date", self.cd_target)
        trow = QHBoxLayout()
        self.cd_timed = QCheckBox("At a set time")
        self.cd_timed.toggled.connect(self._changed)
        self.cd_time = QTimeEdit()
        self.cd_time.setDisplayFormat("HH:mm")
        self.cd_time.timeChanged.connect(self._changed)
        trow.addWidget(self.cd_timed)
        trow.addWidget(self.cd_time)
        trow.addStretch(1)
        f.addRow("", trow)
        self.cd_start = QDateEdit()
        self.cd_start.setCalendarPopup(True)
        self.cd_start.setDisplayFormat("ddd d MMM yyyy")
        self.cd_start.dateChanged.connect(self._changed)
        f.addRow("Count from", self.cd_start)
        h = QLabel("The pie fills from “count from” to the target date — "
                   "e.g. the day you booked the trip.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        f.addRow("", h)
        return w

    def _counter_page(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setHorizontalSpacing(12)
        f.setVerticalSpacing(8)
        row = QHBoxLayout()
        self.ct_current = NumBox()
        self.ct_current.valueChanged.connect(self._changed)
        self.ct_total = NumBox(0.01)
        self.ct_total.valueChanged.connect(self._changed)
        self.ct_unit = QLineEdit()
        self.ct_unit.setPlaceholderText("pages, chapters, km…")
        self.ct_unit.textChanged.connect(self._changed)
        row.addWidget(self.ct_current, 1)
        row.addWidget(QLabel("of"))
        row.addWidget(self.ct_total, 1)
        row.addWidget(self.ct_unit, 2)
        f.addRow("Progress", row)
        self.ct_step = NumBox(0.01)
        self.ct_step.valueChanged.connect(self._changed)
        self.ct_step.setToolTip("How much one scroll notch or +/- changes it")
        f.addRow("Step", self.ct_step)
        self.ct_started = QDateEdit()
        self.ct_started.setCalendarPopup(True)
        self.ct_started.setDisplayFormat("ddd d MMM yyyy")
        self.ct_started.dateChanged.connect(self._changed)
        f.addRow("Started on", self.ct_started)
        drow = QHBoxLayout()
        self.ct_has_deadline = QCheckBox("Finish by")
        self.ct_has_deadline.toggled.connect(self._changed)
        self.ct_deadline = QDateEdit()
        self.ct_deadline.setCalendarPopup(True)
        self.ct_deadline.setDisplayFormat("ddd d MMM yyyy")
        self.ct_deadline.dateChanged.connect(self._changed)
        drow.addWidget(self.ct_has_deadline)
        drow.addWidget(self.ct_deadline)
        drow.addStretch(1)
        f.addRow("Deadline", drow)
        h = QLabel("The start date gives your pace and a finish estimate (hover the "
                   "pie). With a deadline the card shows how much per day you need.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        f.addRow("", h)
        return w

    def _period_page(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setHorizontalSpacing(12)
        self.pd_kind = QComboBox()
        for p in model.PERIODS:
            self.pd_kind.addItem(f"This {p}", p)
        self.pd_kind.currentIndexChanged.connect(self._changed)
        f.addRow("Track", self.pd_kind)
        h = QLabel("Fills on its own. Leave the name blank to show the current "
                   "year / month / week number.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        f.addRow("", h)
        return w

    # ------------------------------------------------------------------ #
    # list
    # ------------------------------------------------------------------ #
    def _fill_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        for t in self.items:
            self.list.addItem(self._item(t))
        self.list.blockSignals(False)

    def _item(self, t) -> QListWidgetItem:
        it = QListWidgetItem(_dot(t["color"]), self._label(t))
        it.setData(Qt.UserRole, t["id"])
        return it

    def _label(self, t) -> str:
        name = model.display_name(t)
        return name if t.get("visible", True) else f"{name}  (hidden)"

    def _current(self) -> dict | None:
        it = self.list.currentItem()
        if it is None:
            return None
        tid = it.data(Qt.UserRole)
        return next((t for t in self.items if t["id"] == tid), None)

    def _on_reorder(self, *_):
        order = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]
        by_id = {t["id"]: t for t in self.items}
        self.items = [by_id[i] for i in order if i in by_id]

    def _next_color(self) -> str:
        used = [t["color"].upper() for t in self.items]
        for c in model.PALETTE:
            if c.upper() not in used:
                return c
        return model.PALETTE[len(self.items) % len(model.PALETTE)]

    def _add(self, kind):
        t = model.default_tracker(kind, color=self._next_color())
        self.items.append(t)
        self.list.addItem(self._item(t))
        self.list.setCurrentRow(self.list.count() - 1)
        self.name.setFocus()
        self.name.selectAll()
        self._sync_enabled()

    def _duplicate(self):
        t = self._current()
        if not t:
            return
        c = copy.deepcopy(t)
        c["id"] = model.new_id()
        c["name"] = (t.get("name") or model.display_name(t)) + " (copy)"
        row = self.list.currentRow() + 1
        self.items.insert(row, c)
        self.list.insertItem(row, self._item(c))
        self.list.setCurrentRow(row)

    def _delete(self):
        t = self._current()
        if not t:
            return
        if QMessageBox.question(
                self, "Delete tracker",
                f"Delete “{model.display_name(t)}”?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        row = self.list.currentRow()
        self.items = [x for x in self.items if x["id"] != t["id"]]
        self.list.takeItem(row)
        self._sync_enabled()

    def _sync_enabled(self):
        has = self._current() is not None
        for w in (self.form_box, self.pages, self.dup_btn, self.del_btn):
            w.setEnabled(has)
        if not has:
            self._show_preview(None)

    # ------------------------------------------------------------------ #
    # form <-> tracker
    # ------------------------------------------------------------------ #
    def _on_select(self, _row):
        t = self._current()
        self._sync_enabled()
        if not t:
            return
        self._loading = True
        try:
            self.name.setText(t.get("name", ""))
            self.name.setPlaceholderText(
                "(automatic)" if t["type"] == "period" else "e.g. Lisbon trip")
            self.kind.setCurrentIndex(model.TYPES.index(t["type"]))
            self.pages.setCurrentIndex(model.TYPES.index(t["type"]))
            self.reverse.setCurrentIndex(1 if t.get("reverse") else 0)
            self.visible.setChecked(bool(t.get("visible", True)))
            self._mark_swatch(t["color"])
            if t["type"] == "countdown":
                self.cd_target.setDate(_qdate(t["target"]))
                self.cd_start.setDate(_qdate(t["start"]))
                timed = model.has_time(t["target"])
                self.cd_timed.setChecked(timed)
                tt = model.parse_when(t["target"])
                self.cd_time.setTime(QTime(tt.hour, tt.minute) if timed else QTime(9, 0))
                self.cd_time.setEnabled(timed)
            elif t["type"] == "counter":
                self.ct_total.setValue(float(t["total"]))
                self.ct_current.setValue(float(t["current"]))
                self.ct_unit.setText(t.get("unit", ""))
                self.ct_step.setValue(float(t.get("step", 1)))
                self.ct_started.setDate(_qdate(t["started"]))
                dl = t.get("deadline") or ""
                self.ct_has_deadline.setChecked(bool(dl))
                self.ct_deadline.setDate(_qdate(dl) if dl else
                                         QDate.currentDate().addMonths(1))
                self.ct_deadline.setEnabled(bool(dl))
            else:
                self.pd_kind.setCurrentIndex(model.PERIODS.index(t.get("period", "year")))
        finally:
            self._loading = False
        self._show_preview(t)

    def _changed(self, *_):
        if self._loading:
            return
        t = self._current()
        if not t:
            return
        t["name"] = self.name.text().strip()
        t["reverse"] = bool(self.reverse.currentData())
        t["visible"] = self.visible.isChecked()
        if t["type"] == "countdown":
            target = _iso(self.cd_target.date())
            self.cd_time.setEnabled(self.cd_timed.isChecked())
            if self.cd_timed.isChecked():
                target += "T" + self.cd_time.time().toString("HH:mm")
            t["target"] = target
            t["start"] = _iso(self.cd_start.date())
        elif t["type"] == "counter":
            t["total"] = model._num(self.ct_total.value(), 1) or 1
            t["unit"] = self.ct_unit.text().strip()
            t["step"] = model._num(self.ct_step.value(), 1) or 1
            t["started"] = _iso(self.ct_started.date())
            new_cur = model._num(self.ct_current.value(), 0)
            if new_cur != t.get("current"):
                model.set_counter(t, new_cur)
            self.ct_deadline.setEnabled(self.ct_has_deadline.isChecked())
            t["deadline"] = (_iso(self.ct_deadline.date())
                             if self.ct_has_deadline.isChecked() else "")
        else:
            t["period"] = self.pd_kind.currentData()
        it = self.list.currentItem()
        if it is not None:
            it.setText(self._label(t))
        self._show_preview(t)

    def _kind_changed(self, idx):
        if self._loading:
            return
        t = self._current()
        if not t:
            return
        kind = model.TYPES[idx]
        if kind == t["type"]:
            return
        fresh = model.default_tracker(kind, color=t["color"])
        keep_name = t.get("name") if t.get("name") not in (
            "New countdown", "New counter") else ""
        fresh.update({"id": t["id"], "name": keep_name or fresh["name"],
                      "reverse": t.get("reverse", False),
                      "visible": t.get("visible", True)})
        t.clear()
        t.update(fresh)
        self._on_select(self.list.currentRow())

    def _mark_swatch(self, color: str):
        for c, b in self.swatches:
            ring = "#ffffff" if c.upper() == color.upper() else "rgba(0,0,0,0)"
            b.setStyleSheet(f"background: {c}; border: 2px solid {ring};")

    def _set_color(self, color: str):
        t = self._current()
        if not t:
            return
        t["color"] = color
        self._mark_swatch(color)
        it = self.list.currentItem()
        if it is not None:
            it.setIcon(_dot(color))
        self._show_preview(t)

    def _pick_color(self):
        t = self._current()
        if not t:
            return
        c = QColorDialog.getColor(QColor(t["color"]), self, "Tracker colour")
        if c.isValid():
            self._set_color(c.name().upper())

    def _show_preview(self, t):
        if self.preview is not None:
            self.preview.setParent(None)
            self.preview.deleteLater()
            self.preview = None
        if t is None:
            return
        card = PieCard(t, self.cfg)
        card.set_status(model.evaluate(t), model.display_name(t))
        w = card.natural_text_width()
        if self.cfg.get("layout") == "pies":
            d = card.pie_size()
            w = max(d, min(w, int(d * 1.7)))
        else:
            w = max(150, min(w, 300))
        card.apply_size(w)
        self.preview_host.addWidget(card)
        self.preview = card

    # ------------------------------------------------------------------ #
    def result_trackers(self) -> list[dict]:
        self._on_reorder()
        return self.items
