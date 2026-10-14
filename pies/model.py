"""Tracker types and the maths behind each pie. No Qt in here.

Every tracker is a plain dict (that is what lands in trackers.json). The
`evaluate()` function turns one into a `Status`: how full the pie is, and the
lines of text shown next to it.

Types
-----
countdown   days left until a date (optionally a date + time).
            The pie fills from `start` to `target`.
counter     current / total of something: pages, chapters, episodes, km...
            Updated by hand (scroll wheel over the pie, menu, or --add).
period      how far through the current day / week / month / year.
"""
from __future__ import annotations

import calendar
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

TYPES = ("countdown", "counter", "period")
TYPE_LABELS = {
    "countdown": "Countdown to a date",
    "counter": "Counter (x of y)",
    "period": "Day / week / month / year",
}
PERIODS = ("day", "week", "month", "year")

PALETTE = [
    "#3FC1E0", "#56D07A", "#E0A03F", "#7C6CE8",
    "#E04FB0", "#E0703F", "#9BD04F", "#4FA8E0",
    "#D2526E", "#E0C13F",
]


# --------------------------------------------------------------------------- #
# construction / validation
# --------------------------------------------------------------------------- #
def new_id() -> str:
    return uuid.uuid4().hex[:8]


def default_tracker(kind: str, today: date | None = None,
                    color: str | None = None) -> dict:
    today = today or date.today()
    base = {
        "id": new_id(),
        "name": "",
        "type": kind,
        "color": color or PALETTE[0],
        "reverse": False,   # pie shows what is LEFT instead of what is done
        "visible": True,
    }
    if kind == "countdown":
        base.update({
            "name": "New countdown",
            "start": today.isoformat(),
            "target": (today + timedelta(days=30)).isoformat(),
        })
    elif kind == "counter":
        base.update({
            "name": "New counter",
            "current": 0,
            "total": 100,
            "unit": "",
            "step": 1,
            "started": today.isoformat(),
            "deadline": "",
            "log": [[today.isoformat(), 0]],
        })
    elif kind == "period":
        base.update({"name": "", "period": "year"})
    return base


def normalize(t: dict, today: date | None = None) -> dict:
    """Fill in missing keys and coerce types so the rest of the code can trust
    the dict. Unknown keys are kept (hand-edited JSON should survive a save)."""
    today = today or date.today()
    kind = t.get("type") if t.get("type") in TYPES else "counter"
    out = default_tracker(kind, today)
    out.update({k: v for k, v in t.items() if v is not None})
    out["type"] = kind
    out["id"] = str(out.get("id") or new_id())
    out["name"] = str(out.get("name") or "")
    out["reverse"] = bool(out.get("reverse"))
    out["visible"] = bool(out.get("visible", True))
    if not _is_color(out.get("color")):
        out["color"] = PALETTE[0]

    if kind == "countdown":
        if parse_when(out.get("target")) is None:
            out["target"] = (today + timedelta(days=30)).isoformat()
        if parse_when(out.get("start")) is None:
            out["start"] = today.isoformat()
    elif kind == "counter":
        out["current"] = _num(out.get("current"), 0)
        out["total"] = _num(out.get("total"), 100) or 1
        out["step"] = _num(out.get("step"), 1) or 1
        out["unit"] = str(out.get("unit") or "")
        if parse_when(out.get("started")) is None:
            out["started"] = today.isoformat()
        if out.get("deadline") and parse_when(out["deadline"]) is None:
            out["deadline"] = ""
        log = t.get("log")
        if not isinstance(log, list):
            log = []
        clean = []
        for row in log:
            try:
                d = date.fromisoformat(str(row[0])[:10])
                clean.append([d.isoformat(), _num(row[1], 0)])
            except Exception:
                continue
        out["log"] = clean or [[today.isoformat(), out["current"]]]
    elif kind == "period":
        if out.get("period") not in PERIODS:
            out["period"] = "year"
    return out


def _is_color(v) -> bool:
    return isinstance(v, str) and len(v) == 7 and v.startswith("#") and all(
        c in "0123456789abcdefABCDEF" for c in v[1:])


def _num(v, fallback):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return fallback
        return int(f) if f.is_integer() else f
    except Exception:
        return fallback


def parse_when(s) -> datetime | None:
    """'2026-11-02' -> midnight that day; '2026-11-02T18:30' -> that minute."""
    if not s or not isinstance(s, str):
        return None
    try:
        if len(s) <= 10:
            return datetime.combine(date.fromisoformat(s), datetime.min.time())
        return datetime.fromisoformat(s).replace(tzinfo=None, second=0,
                                                  microsecond=0)
    except Exception:
        return None


def has_time(s: str) -> bool:
    return isinstance(s, str) and len(s) > 10


# --------------------------------------------------------------------------- #
# counter mutation
# --------------------------------------------------------------------------- #
def set_counter(t: dict, value: float, today: date | None = None) -> None:
    """Set a counter's value and record it in the per-day log (one row/day)."""
    today = today or date.today()
    v = _num(value, t.get("current", 0))
    v = max(0, v)
    t["current"] = v
    key = today.isoformat()
    log = t.setdefault("log", [])
    if log and log[-1][0] == key:
        log[-1][1] = v
    else:
        log.append([key, v])
    if len(log) > 400:
        del log[1:len(log) - 399]   # keep the first row: it anchors the pace


def bump_counter(t: dict, delta: float, today: date | None = None) -> None:
    set_counter(t, _num(t.get("current"), 0) + delta, today)


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #
def fmt_num(v) -> str:
    v = _num(v, 0)
    if isinstance(v, int):
        return f"{v:,}"
    return f"{v:,.1f}".rstrip("0").rstrip(".")


def fmt_pct(frac: float) -> str:
    p = frac * 100
    if 0 < p < 1:
        return "<1%"
    if 99 < p < 100:
        return "99%"
    return f"{p:.0f}%"


def fmt_date(d: date, today: date) -> str:
    if d.year == today.year:
        return d.strftime("%a %d %b").replace(" 0", " ")
    return d.strftime("%d %b %Y").lstrip("0")


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def fmt_span(seconds: float) -> str:
    """Rough human duration: '3 days', '5 h 12 m', '14 min'."""
    s = max(0, int(seconds))
    if s >= 2 * 86400:
        return plural(s // 86400, "day")
    if s >= 3600:
        h, m = divmod(s // 60, 60)
        return f"{h} h {m:02d} m"
    if s >= 60:
        return f"{s // 60} min"
    return f"{s} s"


def weeks_days(n: int) -> str:
    w, d = divmod(abs(n), 7)
    if not w:
        return plural(d, "day")
    return plural(w, "week") + (f" {plural(d, 'day')}" if d else "")


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
@dataclass
class Status:
    fraction: float      # 0..1, share that is DONE
    value: str           # main line, e.g. "12 days left"
    detail: str          # second line, e.g. "63% · Sun 20 Sep"
    tooltip: str
    done: bool = False

    def shown(self, reverse: bool) -> float:
        """Share of the pie to paint."""
        return 1.0 - self.fraction if reverse else self.fraction


def display_name(t: dict, now: datetime | None = None) -> str:
    if t.get("name"):
        return t["name"]
    now = now or datetime.now()
    if t.get("type") == "period":
        p = t.get("period", "year")
        if p == "year":
            return str(now.year)
        if p == "month":
            return now.strftime("%B")
        if p == "week":
            return f"Week {now.isocalendar()[1]}"
        return "Today"
    return "Untitled"


def evaluate(t: dict, now: datetime | None = None) -> Status:
    now = now or datetime.now()
    kind = t.get("type")
    try:
        if kind == "countdown":
            return _eval_countdown(t, now)
        if kind == "counter":
            return _eval_counter(t, now)
        if kind == "period":
            return _eval_period(t, now)
    except Exception as e:  # a hand-edited file should never kill the widget
        return Status(0.0, "invalid", str(e)[:40], f"Could not evaluate: {e}")
    return Status(0.0, "unknown type", str(kind), "")


def _clamp(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _eval_countdown(t: dict, now: datetime) -> Status:
    today = now.date()
    target = parse_when(t["target"])
    start = parse_when(t.get("start")) or target
    timed = has_time(t["target"])
    span = (target - start).total_seconds()
    frac = 1.0 if span <= 0 else _clamp((now - start).total_seconds() / span)
    when = fmt_date(target.date(), today) + (target.strftime(" %H:%M") if timed else "")

    if timed:
        left = (target - now).total_seconds()
        done = left <= 0
        if done:
            ago = -left
            value = "Now!" if ago < 3600 else f"{fmt_span(ago)} ago"
        else:
            value = f"{fmt_span(left)} left"
        days_left = (target.date() - today).days
    else:
        days_left = (target.date() - today).days
        done = days_left <= 0
        if days_left > 1:
            value = f"{days_left:,} days left"
        elif days_left == 1:
            value = "Tomorrow"
        elif days_left == 0:
            value = "Today!"
        else:
            value = f"{plural(-days_left, 'day')} ago"
        if done:
            frac = 1.0

    detail = f"{fmt_pct(frac)}  ·  {when}"
    tip = [display_name(t, now), f"Target: {target:%A %d %B %Y}"
           + (f" {target:%H:%M}" if timed else "")]
    if days_left > 0:
        tip.append(f"{weeks_days(days_left)} to go"
                   + (f"  ({days_left // 30} months)" if days_left >= 60 else ""))
    total_days = (target.date() - start.date()).days
    if total_days > 0:
        elapsed = min(max((today - start.date()).days, 0), total_days)
        tip.append(f"Counting from {start:%d %b %Y}: day {elapsed} of {total_days}")
    tip.append(f"{frac * 100:.1f}% of the wait is over")
    return Status(frac, value, detail, "\n".join(tip), done)


def _pace(t: dict, today: date):
    """Average units per day since `started` (counting today), or None.

    Counting from zero on the start date keeps it intuitive: start a book on
    the 1st, be on page 120 on the 12th -> 10 pages a day.
    """
    try:
        d0 = date.fromisoformat(str(t.get("started", ""))[:10])
    except Exception:
        return None
    days = (today - d0).days + 1
    cur = float(t.get("current", 0))
    if days < 1 or cur <= 0:
        return None
    return cur / days


def _eval_counter(t: dict, now: datetime) -> Status:
    today = now.date()
    cur = float(t.get("current", 0))
    total = float(t.get("total", 1)) or 1.0
    unit = t.get("unit", "")
    frac = _clamp(cur / total)
    done = cur >= total
    remaining = max(0.0, total - cur)

    value = f"{fmt_num(cur)} / {fmt_num(total)}" + (f" {unit}" if unit else "")
    tip = [display_name(t, now), value, f"{frac * 100:.1f}% done"]

    deadline = parse_when(t.get("deadline") or "")
    pace = _pace(t, today)
    if done:
        detail = "Done ✓"
    else:
        rem_txt = fmt_num(remaining) + (f" {unit}" if unit else "")
        tip.append(f"{rem_txt} to go")
        detail = f"{fmt_pct(frac)}  ·  {rem_txt} left"
        if deadline is not None:
            days = (deadline.date() - today).days
            if days > 0:
                need = remaining / days
                per = f"{fmt_num(round(need, 1))}{(' ' + unit) if unit else ''}/day"
                detail = f"{fmt_pct(frac)}  ·  {per}"
                tip.append(f"Deadline {fmt_date(deadline.date(), today)}: "
                           f"{per} needed over {plural(days, 'day')}")
            else:
                detail = f"{fmt_pct(frac)}  ·  deadline passed"
                tip.append(f"Deadline was {fmt_date(deadline.date(), today)}")
        if pace:
            eta = today + timedelta(days=math.ceil(remaining / pace))
            tip.append(f"Your pace: {fmt_num(round(pace, 1))}"
                       f"{(' ' + unit) if unit else ''}/day "
                       f"→ finish around {fmt_date(eta, today)}")
    tip.append(f"Started {t.get('started', '')[:10]}")
    return Status(frac, value, detail, "\n".join(tip), done)


def period_bounds(kind: str, now: datetime) -> tuple[datetime, datetime]:
    d = now.date()
    if kind == "day":
        s = datetime.combine(d, datetime.min.time())
        return s, s + timedelta(days=1)
    if kind == "week":
        s = datetime.combine(d - timedelta(days=d.weekday()), datetime.min.time())
        return s, s + timedelta(days=7)
    if kind == "month":
        s = datetime(d.year, d.month, 1)
        n = calendar.monthrange(d.year, d.month)[1]
        return s, s + timedelta(days=n)
    s = datetime(d.year, 1, 1)
    return s, datetime(d.year + 1, 1, 1)


def _eval_period(t: dict, now: datetime) -> Status:
    kind = t.get("period", "year")
    s, e = period_bounds(kind, now)
    frac = _clamp((now - s).total_seconds() / (e - s).total_seconds())
    left = (e - now).total_seconds()
    if kind == "day":
        value = f"{fmt_span(left)} left"
    else:
        days = (e.date() - now.date()).days
        value = f"{plural(days, 'day')} left"
    detail = f"{fmt_pct(frac)} of the {kind} gone"
    tip = [display_name(t, now),
           f"{s:%d %b %Y} → {(e - timedelta(seconds=1)):%d %b %Y}",
           f"{frac * 100:.2f}% elapsed"]
    if kind == "year":
        tip.append(f"Day {now.timetuple().tm_yday} of {(e - s).days}")
    return Status(frac, value, detail, "\n".join(tip), False)


def sample_trackers(today: date | None = None) -> list[dict]:
    """What a brand-new install shows, so the widget isn't empty."""
    today = today or date.today()
    trip = default_tracker("countdown", today, PALETTE[0])
    trip.update({"name": "Example trip",
                 "start": (today - timedelta(days=20)).isoformat(),
                 "target": (today + timedelta(days=24)).isoformat()})
    book = default_tracker("counter", today, PALETTE[2])
    book.update({"name": "Example book", "current": 120, "total": 384,
                 "unit": "pages", "step": 1,
                 "started": (today - timedelta(days=10)).isoformat(),
                 "log": [[(today - timedelta(days=10)).isoformat(), 0],
                         [today.isoformat(), 120]]})
    year = default_tracker("period", today, PALETTE[3])
    year["period"] = "year"
    return [trip, book, year]
