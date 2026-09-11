from __future__ import annotations

import argparse
import json
import locale
import math
import os
import sys
import time
from pathlib import Path

from .core import BusyError, QuartermasterError, Store, advise, ingest, reconcile, select_view, view
from .display import DEFAULT_ROTATE_SECONDS, Rotation, card
from .render import render


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quartermaster")
    p.add_argument(
        "--state-dir",
        type=Path,
        default=Path(
            os.environ.get("QUARTERMASTER_STATE_DIR", "~/.local/state/quartermaster")
        ).expanduser(),
    )
    p.add_argument("--lock-timeout", type=float, default=2.0)
    sub = p.add_subparsers(dest="command", required=True)
    ing = sub.add_parser("ingest")
    ing.add_argument("kind", choices=["cswap", "quota-axi"])
    ing.add_argument("--file", type=Path)
    ing.add_argument("--host", default="local")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.add_argument("--freshness-seconds", type=int, default=300)
    tui = sub.add_parser("tui")
    tui.add_argument("--once", action="store_true")
    tui.add_argument("--refresh", type=float, default=5)
    tui.add_argument(
        "--rotate",
        type=float,
        default=DEFAULT_ROTATE_SECONDS,
        help="Seconds per account (default: 5); 0 holds the selected account",
    )
    tui.add_argument("--compact", action="store_true", help="Use the compact multi-account layout")
    selection = sub.add_parser("view", help="Select an account for the rotating display")
    selection.add_argument(
        "selector",
        help="1-based index, full identity, unique label, auto, or a disambiguating type:value",
    )
    adv = sub.add_parser("advise")
    adv.add_argument("--request-id", required=True)
    adv.add_argument("--provider", required=True)
    adv.add_argument("--model")
    adv.add_argument("--reserve", type=float, default=10)
    adv.add_argument("--metadata-json", default="{}")
    rec = sub.add_parser("reconcile")
    rec.add_argument("request_id")
    rec.add_argument("event", choices=["cancel", "launch", "complete"])
    rec.add_argument("--process-id")
    return p


def _plain(report: dict) -> str:
    return "\n".join(render(report, 80, max(6, len(report["accounts"]) + 4)))


def _terminal_locale() -> str:
    original = locale.setlocale(locale.LC_CTYPE)
    for candidate in ("", "C.UTF-8", "UTF-8", "en_US.UTF-8"):
        try:
            locale.setlocale(locale.LC_CTYPE, candidate)
        except locale.Error:
            continue
        if locale.nl_langinfo(locale.CODESET).replace("-", "").lower() == "utf8":
            return original
    locale.setlocale(locale.LC_CTYPE, original)
    raise QuartermasterError("A UTF-8 locale is required for the terminal display")


def _tui(
    store: Store,
    once: bool,
    refresh: float,
    rotate: float = DEFAULT_ROTATE_SECONDS,
    compact: bool = False,
) -> None:
    if not math.isfinite(refresh) or refresh <= 0:
        raise QuartermasterError("--refresh must be finite and greater than zero")
    if not math.isfinite(rotate) or rotate < 0:
        raise QuartermasterError("--rotate must be finite and nonnegative")
    rotation = Rotation(rotate)

    def frame(report, width, height):
        if compact:
            return render(report, width, height)
        account = rotation.update(report, time.monotonic())
        return card(report, account, width, height, rotation.manual or rotate == 0, time.time())

    if once or not (sys.stdin.isatty() and sys.stdout.isatty()):
        size = os.get_terminal_size() if sys.stdout.isatty() else os.terminal_size((80, 24))
        print("\n".join(frame(view(store.read()), size.columns, size.lines)))
        return
    try:
        import curses
    except ImportError as exc:
        raise QuartermasterError("curses unavailable; use status or tui --once") from exc

    def run(screen):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.keypad(True)
        screen.attrset(curses.A_BOLD)
        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
            screen.bkgd(" ", curses.color_pair(1))
            screen.attrset(curses.color_pair(1) | curses.A_BOLD)
        screen.nodelay(True)
        while True:
            report = view(store.read())
            height, width = screen.getmaxyx()
            screen.erase()
            for row, line in enumerate(frame(report, width, height)):
                try:
                    screen.addstr(row, 0, line)
                except curses.error:
                    pass
            screen.refresh()
            deadline = time.monotonic() + refresh
            if not compact and not rotation.manual and rotate > 0 and rotation.due is not None:
                deadline = min(deadline, rotation.due)
            while time.monotonic() < deadline:
                key = screen.getch()
                if key in (ord("q"), 27):
                    return
                if key == curses.KEY_RESIZE:
                    break
                if not compact:
                    action = {
                        ord(" "): "next",
                        curses.KEY_RIGHT: "next",
                        curses.KEY_LEFT: "previous",
                    }.get(key)
                    if action is None and key in [ord(c) for c in "0123456789r"]:
                        action = chr(key)
                    if action is not None:
                        rotation.key(action, report, time.monotonic())
                        break
                time.sleep(0.05)

    original_locale = _terminal_locale()
    try:
        curses.wrapper(run)
    finally:
        locale.setlocale(locale.LC_CTYPE, original_locale)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    store = Store(args.state_dir, args.lock_timeout)
    try:
        if args.command == "ingest":
            text = args.file.read_text() if args.file else sys.stdin.read()
            result = ingest(store, args.kind, json.loads(text), args.host)
            print(json.dumps(result, indent=2))
        elif args.command == "status":
            result = view(store.read(), freshness_seconds=args.freshness_seconds)
            print(json.dumps(result, indent=2) if args.json else _plain(result))
        elif args.command == "tui":
            _tui(store, args.once, args.refresh, args.rotate, args.compact)
        elif args.command == "view":
            print(json.dumps(select_view(store, args.selector), indent=2))
        elif args.command == "advise":
            result = advise(
                store,
                args.request_id,
                args.provider,
                args.model,
                json.loads(args.metadata_json),
                args.reserve,
            )
            print(json.dumps(result, indent=2))
        else:
            print(
                json.dumps(reconcile(store, args.request_id, args.event, args.process_id), indent=2)
            )
        return 0
    except BusyError as exc:
        print(json.dumps({"error": "BUSY", "message": str(exc)}), file=sys.stderr)
        return 75
    except (QuartermasterError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"error": "UNKNOWN", "message": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
