from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .core import BusyError, QuartermasterError, Store, advise, ingest, reconcile, view
from .render import render


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quartermaster")
    p.add_argument("--state-dir", type=Path, default=Path(os.environ.get("QUARTERMASTER_STATE_DIR", "~/.local/state/quartermaster")).expanduser())
    p.add_argument("--lock-timeout", type=float, default=2.0)
    sub = p.add_subparsers(dest="command", required=True)
    ing = sub.add_parser("ingest"); ing.add_argument("kind", choices=["cswap", "quota-axi"]); ing.add_argument("--file", type=Path); ing.add_argument("--host", default="local")
    status = sub.add_parser("status"); status.add_argument("--json", action="store_true"); status.add_argument("--freshness-seconds", type=int, default=300)
    tui = sub.add_parser("tui"); tui.add_argument("--once", action="store_true"); tui.add_argument("--refresh", type=float, default=5)
    adv = sub.add_parser("advise"); adv.add_argument("--request-id", required=True); adv.add_argument("--provider", required=True); adv.add_argument("--model"); adv.add_argument("--reserve", type=float, default=10); adv.add_argument("--metadata-json", default="{}")
    rec = sub.add_parser("reconcile"); rec.add_argument("request_id"); rec.add_argument("event", choices=["cancel", "launch", "complete"]); rec.add_argument("--process-id")
    return p


def _plain(report: dict) -> str:
    return "\n".join(render(report, 80, max(6, len(report["accounts"]) + 4)))


def _tui(store: Store, once: bool, refresh: float) -> None:
    if once or not (sys.stdin.isatty() and sys.stdout.isatty()):
        size = os.get_terminal_size() if sys.stdout.isatty() else os.terminal_size((80, 24))
        print("\n".join(render(view(store.read()), size.columns, size.lines)))
        return
    try:
        import curses
    except ImportError as exc:
        raise QuartermasterError("curses unavailable; use status or tui --once") from exc
    def run(screen):
        curses.curs_set(0); screen.nodelay(True)
        while True:
            height, width = screen.getmaxyx(); screen.erase()
            for row, line in enumerate(render(view(store.read()), width, height)):
                try: screen.addnstr(row, 0, line, max(0, width - 1))
                except curses.error: pass
            screen.refresh()
            deadline = time.monotonic() + refresh
            while time.monotonic() < deadline:
                key = screen.getch()
                if key in (ord("q"), 27): return
                if key == curses.KEY_RESIZE: break
                time.sleep(0.05)
    curses.wrapper(run)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv); store = Store(args.state_dir, args.lock_timeout)
    try:
        if args.command == "ingest":
            text = args.file.read_text() if args.file else sys.stdin.read()
            result = ingest(store, args.kind, json.loads(text), args.host); print(json.dumps(result, indent=2))
        elif args.command == "status":
            result = view(store.read(), freshness_seconds=args.freshness_seconds)
            print(json.dumps(result, indent=2) if args.json else _plain(result))
        elif args.command == "tui": _tui(store, args.once, args.refresh)
        elif args.command == "advise":
            result = advise(store, args.request_id, args.provider, args.model, json.loads(args.metadata_json), args.reserve); print(json.dumps(result, indent=2))
        else: print(json.dumps(reconcile(store, args.request_id, args.event, args.process_id), indent=2))
        return 0
    except BusyError as exc:
        print(json.dumps({"error": "BUSY", "message": str(exc)}), file=sys.stderr); return 75
    except (QuartermasterError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"error": "UNKNOWN", "message": str(exc)}), file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
