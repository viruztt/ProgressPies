"""One tracker on the widget: a pie (or donut) plus up to three lines of text."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QWidget

from . import model

BG = QColor(14, 15, 20, 225)
CARD_BG = QColor(26, 28, 36, 235)
TEXT = QColor(238, 240, 245)
MUTED = QColor(150, 156, 170)
TRACK = QColor(255, 255, 255, 30)
INK = QColor(12, 13, 17)


def paint_pie(p: QPainter, r: QRectF, frac: float, accent: QColor,
              style: str = "pie", done: bool = False, center: str = "",
              font: QFont | None = None) -> None:
    """Draw a progress pie filling clockwise from 12 o'clock."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    frac = max(0.0, min(1.0, frac))
    full = frac >= 0.9995

    if style == "donut":
        w = max(3.0, r.width() * 0.17)
        ar = r.adjusted(w / 2, w / 2, -w / 2, -w / 2)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(TRACK, w, Qt.SolidLine, Qt.FlatCap))
        p.drawEllipse(ar)
        if frac > 0:
            cap = Qt.FlatCap if full or frac < 0.02 else Qt.RoundCap
            p.setPen(QPen(accent, w, Qt.SolidLine, cap))
            if full:
                p.drawEllipse(ar)
            else:
                p.drawArc(ar, 90 * 16, -max(1, int(round(frac * 5760))))
        if done:
            _check(p, r.adjusted(w, w, -w, -w), accent)
        elif center and r.width() >= 30:
            f = QFont(font) if font else QFont()
            f.setBold(True)
            f.setPixelSize(max(7, int(r.height() * 0.24)))
            p.setFont(f)
            p.setPen(TEXT)
            p.drawText(r, Qt.AlignCenter, center)
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(TRACK)
        p.drawEllipse(r)
        if frac > 0:
            p.setBrush(accent)
            if full:
                p.drawEllipse(r)
            else:
                p.drawPie(r, 90 * 16, -max(1, int(round(frac * 5760))))
        edge = QColor(accent)
        edge.setAlpha(120)
        p.setPen(QPen(edge, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))
        if done:
            _check(p, r, INK if full else accent)
    p.restore()


def _check(p: QPainter, r: QRectF, color: QColor) -> None:
    path = QPainterPath(QPointF(r.left() + r.width() * 0.27,
                                r.top() + r.height() * 0.52))
    path.lineTo(r.left() + r.width() * 0.44, r.top() + r.height() * 0.68)
    path.lineTo(r.left() + r.width() * 0.74, r.top() + r.height() * 0.35)
    p.setPen(QPen(color, max(2.0, r.width() * 0.09), Qt.SolidLine,
                  Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


class PieCard(QWidget):
    edit_requested = Signal(str)
    adjust_requested = Signal(str, float)

    PAD = 8

    def __init__(self, tracker: dict, cfg: dict, parent=None):
        super().__init__(parent)
        self.tracker = tracker
        self.tid = tracker["id"]
        self.cfg = cfg
        self.status = model.Status(0.0, "", "", "")
        self.name = ""
        self._hover = False
        self._wheel_acc = 0
        self.text_w = 160
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        f = QFont(self.font())
        f.setPointSize(int(cfg.get("font_size", 10)))
        self.setFont(f)

    # -- fonts / geometry --------------------------------------------- #
    def _fonts(self):
        base = QFont(self.font())
        name = QFont(base)
        name.setBold(True)
        name.setPointSizeF(max(7.0, base.pointSizeF() - 0.5))
        value = QFont(base)
        value.setBold(True)
        value.setPointSizeF(base.pointSizeF() + 1.5)
        detail = QFont(base)
        detail.setPointSizeF(max(7.0, base.pointSizeF() - 1.0))
        return name, value, detail

    def _pies_only(self) -> bool:
        return self.cfg.get("layout") == "pies"

    def pie_size(self) -> int:
        n, v, d = (QFontMetrics(f) for f in self._fonts())
        text_h = n.height() + v.height() + d.height()
        if self._pies_only():
            return int(text_h * 1.15)
        return text_h

    def natural_text_width(self) -> int:
        n, v, d = (QFontMetrics(f) for f in self._fonts())
        if self._pies_only():
            return max(n.horizontalAdvance(self.name),
                       d.horizontalAdvance(self.status.value)) + 4
        return max(n.horizontalAdvance(self.name),
                   v.horizontalAdvance(self.status.value),
                   d.horizontalAdvance(self.status.detail)) + 4

    def apply_size(self, text_w: int) -> None:
        self.text_w = text_w
        self.setFixedSize(self.sizeHint())
        self.update()

    def sizeHint(self) -> QSize:
        d = self.pie_size()
        pad = self.PAD
        if self._pies_only():
            name_f, _, detail_f = self._fonts()
            w = max(d, self.text_w) + 2 * pad
            return QSize(w, pad + d + 4 + QFontMetrics(name_f).height()
                         + QFontMetrics(detail_f).height() + pad - 2)
        return QSize(pad + d + 10 + self.text_w + pad, d + 2 * pad)

    # -- data --------------------------------------------------------- #
    def set_status(self, status: model.Status, name: str) -> None:
        self.status = status
        self.name = name
        tip = status.tooltip
        if self.tracker.get("type") == "counter" and self.cfg.get("wheel_adjust", True):
            step = model.fmt_num(self.tracker.get("step", 1))
            tip += f"\n\nScroll over the pie to change by {step}"
        self.setToolTip(tip + "\nDouble-click to edit")
        self.update()

    # -- events ------------------------------------------------------- #
    def enterEvent(self, _):
        self._hover = True
        self.update()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.edit_requested.emit(self.tid)
            e.accept()

    def wheelEvent(self, e):
        if self.tracker.get("type") != "counter" or not self.cfg.get("wheel_adjust", True):
            e.ignore()
            return
        self._wheel_acc += e.angleDelta().y()
        notches = int(self._wheel_acc / 120)
        if notches:
            self._wheel_acc -= notches * 120
            step = float(self.tracker.get("step", 1) or 1)
            self.adjust_requested.emit(self.tid, notches * step)
        e.accept()

    # -- painting ----------------------------------------------------- #
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        accent = QColor(self.tracker.get("color", "#3FC1E0"))

        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.fillPath(path, CARD_BG)
        border = QColor(accent)
        border.setAlpha(170 if self._hover else 70)
        p.setPen(QPen(border, 1.0))
        p.drawPath(path)

        name_f, value_f, detail_f = self._fonts()
        d = self.pie_size()
        pad = self.PAD
        shown = self.status.shown(bool(self.tracker.get("reverse")))
        center = model.fmt_pct(shown)
        style = self.cfg.get("chart", "pie")

        if self._pies_only():
            pie = QRectF((self.width() - d) / 2, pad, d, d)
            paint_pie(p, pie, shown, accent, style, self.status.done, center,
                      self.font())
            y = pad + d + 2
            for font, color, text in ((name_f, _soft(accent), self.name),
                                      (detail_f, MUTED, self.status.value)):
                fm = QFontMetrics(font)
                p.setFont(font)
                p.setPen(color)
                line = QRectF(pad - 4, y, self.width() - 2 * pad + 8, fm.height())
                p.drawText(line, Qt.AlignHCenter | Qt.AlignVCenter,
                           fm.elidedText(text, Qt.ElideRight, int(line.width())))
                y += fm.height()
            return

        pie = QRectF(pad, pad, d, d)
        paint_pie(p, pie, shown, accent, style, self.status.done, center,
                  self.font())

        x = pad + d + 10
        w = self.width() - x - pad
        y = pad
        for font, color, text in ((name_f, _soft(accent), self.name),
                                  (value_f, TEXT, self.status.value),
                                  (detail_f, MUTED, self.status.detail)):
            fm = QFontMetrics(font)
            p.setFont(font)
            p.setPen(color)
            line = QRectF(x, y, w, fm.height())
            p.drawText(line, Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(text, Qt.ElideRight, int(w)))
            y += fm.height()


def _soft(c: QColor) -> QColor:
    """The accent nudged towards white, so names stay legible on dark cards."""
    return QColor(int(c.red() * 0.75 + 255 * 0.25),
                  int(c.green() * 0.75 + 255 * 0.25),
                  int(c.blue() * 0.75 + 255 * 0.25))
