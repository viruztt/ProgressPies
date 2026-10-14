"""Entry point: python main.py  (or run.bat)

Flags:
  --list                 print every tracker and its progress, then exit
  --add  NAME AMOUNT     add AMOUNT to a counter (negative to subtract)
  --set  NAME VALUE      set a counter to VALUE
  --selftest             check the date maths and the data file, then exit

NAME matches a tracker's name (case-insensitive, a unique prefix is enough) or
its id. A running widget picks up --add / --set within a couple of seconds.
"""
from __future__ import annotations

import sys


def _store():
    from pies import config as cfg_mod
    from pies.store import Store
    cfg = cfg_mod.load()
    return Store(cfg_mod.data_path(cfg))


def list_trackers() -> int:
    from pies import model
    store = _store()
    print(f"Progress Pies  —  {store.path}\n" + "-" * 64)
    if not store.trackers:
        print("(no trackers)")
    for t in store.trackers:
        st = model.evaluate(t)
        bar = "#" * round(st.fraction * 20)
        hidden = "" if t.get("visible", True) else "  [hidden]"
        print(f"{model.display_name(t)[:22]:22} [{bar:20}] {st.fraction * 100:5.1f}%"
              f"  {st.value}{hidden}")
    return 0


def change_counter(args: list[str], mode: str) -> int:
    from pies import model
    if len(args) < 2:
        print(f"usage: main.py --{mode} NAME {'AMOUNT' if mode == 'add' else 'VALUE'}")
        return 2
    name, raw = " ".join(args[:-1]), args[-1]
    try:
        amount = float(raw)
    except ValueError:
        print(f"Not a number: {raw}")
        return 2
    store = _store()
    t = store.find(name)
    if t is None:
        print(f"No tracker matches “{name}”. Try --list.")
        return 1
    if t.get("type") != "counter":
        print(f"“{model.display_name(t)}” is a {t['type']}, not a counter.")
        return 1
    if mode == "add":
        model.bump_counter(t, amount)
    else:
        model.set_counter(t, amount)
    if not store.save():
        print("Could not write the data file.")
        return 1
    st = model.evaluate(t)
    print(f"{model.display_name(t)}: {st.value}  ({st.detail})")
    return 0


def selftest() -> int:
    import tempfile
    from datetime import date, datetime
    from pathlib import Path

    from pies import model
    from pies.store import Store

    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"   -> {got}" if got else ""))

    print("Progress Pies — self-test\n" + "-" * 50)
    now = datetime(2026, 10, 13, 12, 0)

    t = model.normalize({"type": "countdown", "name": "Trip",
                         "start": "2026-10-01", "target": "2026-10-25"})
    st = model.evaluate(t, now)
    check("countdown days left", st.value == "12 days left", st.value)
    check("countdown fraction", abs(st.fraction - 12.5 / 24) < 1e-6, f"{st.fraction:.4f}")
    st = model.evaluate(t, datetime(2026, 10, 24, 9))
    check("countdown tomorrow", st.value == "Tomorrow", st.value)
    st = model.evaluate(t, datetime(2026, 10, 25, 9))
    check("countdown today", st.value == "Today!" and st.done and st.fraction == 1.0, st.value)
    st = model.evaluate(t, datetime(2026, 10, 28, 9))
    check("countdown past", st.value == "3 days ago" and st.done, st.value)
    t2 = model.normalize({"type": "countdown", "start": "2026-10-13",
                          "target": "2026-10-13T18:30"})
    st = model.evaluate(t2, now)
    check("timed countdown", st.value == "6 h 30 m left", st.value)

    b = model.normalize({"type": "counter", "name": "Book", "current": 120,
                         "total": 480, "unit": "pages", "started": "2026-10-02"})
    st = model.evaluate(b, now)
    check("counter value", st.value == "120 / 480 pages", st.value)
    check("counter fraction", abs(st.fraction - 0.25) < 1e-9, f"{st.fraction}")
    check("counter pace in tooltip", "10 pages/day" in st.tooltip,
          st.tooltip.splitlines()[-2])
    model.bump_counter(b, 5, date(2026, 10, 13))
    model.bump_counter(b, 5, date(2026, 10, 13))
    check("counter bump + one log row per day",
          b["current"] == 130 and b["log"][-1] == ["2026-10-13", 130], str(b["log"]))
    b["deadline"] = "2026-10-31"
    st = model.evaluate(b, now)
    check("counter deadline pace", "/day" in st.detail, st.detail)
    model.set_counter(b, 480)
    check("counter done", model.evaluate(b, now).done)

    y = model.normalize({"type": "period", "period": "year"})
    st = model.evaluate(y, now)
    check("year progress", 0.78 < st.fraction < 0.79 and model.display_name(y, now) == "2026",
          f"{st.fraction:.4f}, {st.value}")
    m = model.normalize({"type": "period", "period": "month"})
    check("month progress", model.evaluate(m, now).value == "19 days left",
          model.evaluate(m, now).value)
    w = model.normalize({"type": "period", "period": "week"})
    check("week name", model.display_name(w, now) == "Week 42", model.display_name(w, now))

    bad = model.normalize({"type": "countdown", "target": "not a date", "color": "red"})
    check("bad input repaired", model.parse_when(bad["target"]) is not None
          and bad["color"].startswith("#"))

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "trackers.json"
        s = Store(path)
        check("fresh store seeds examples", len(s.trackers) == 3 and s.created_fresh)
        s.trackers.append(b)
        check("save", s.save())
        again = Store(path)
        check("round-trip", len(again.trackers) == 4
              and again.find("book")["current"] == 480)
        path.write_text("{broken", encoding="utf-8")
        third = Store(path, seed=False)
        check("falls back to .bak when the file is corrupt", len(third.trackers) >= 3,
              f"{len(third.trackers)} trackers")

    print("\nresult:", "ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:  # an old code page shouldn't crash --list over a dash
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    if "--list" in argv:
        return list_trackers()
    for mode in ("add", "set"):
        if f"--{mode}" in argv:
            i = argv.index(f"--{mode}")
            return change_counter(argv[i + 1:], mode)

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 is not installed. Run:\n"
              "    pip install -r requirements.txt", file=sys.stderr)
        return 1

    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    from pies import config as cfg_mod
    from pies import theme
    from pies.store import Store
    from pies.widget import PiesWindow

    cfg = cfg_mod.load()

    app = QApplication(sys.argv)
    app.setApplicationName("Progress Pies")
    theme.apply(app)
    app.setQuitOnLastWindowClosed(False)

    # One instance per data file: two would overwrite each other's edits.
    key = "ProgressPies-" + str(cfg_mod.data_path(cfg)).lower().replace("\\", "-").replace("/", "-")
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(400):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(400)
        probe.disconnectFromServer()
        print("Progress Pies is already running — showing the existing one.")
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    store = Store(cfg_mod.data_path(cfg))
    win = PiesWindow(cfg, store)
    win.show()

    def _second_launch():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        win.show()
        win.raise_()
        win.activateWindow()

    server.newConnection.connect(_second_launch)
    app.aboutToQuit.connect(server.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
