"""Large account cards and an in-process rotation controller; no collection or dispatch."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .core import parse_time
from .render import fit_text

DEFAULT_ROTATE_SECONDS = 5.0  # Ten accounts in 50 seconds; eleven in 55.

# Three-row, three-cell glyphs. Digits use strokes made from terminal blocks.
GLYPHS = {
    "0": ("█▀█", "█ █", "█▄█"),
    "1": (" ▀█", "  █", "  █"),
    "2": ("▀▀█", "█▀▀", "█▄▄"),
    "3": ("▀▀█", " ▀█", "▄▄█"),
    "4": ("█ █", "▀▀█", "  █"),
    "5": ("█▀▀", "▀▀█", "▄▄█"),
    "6": ("█▀▀", "█▀█", "█▄█"),
    "7": ("▀▀█", "  █", "  █"),
    "8": ("█▀█", "█▀█", "█▄█"),
    "9": ("█▀█", "▀▀█", "▄▄█"),
    "?": ("▀▀█", " ▀ ", " ▄ "),
    "%": ("█ ▄", " ▄ ", "▄ █"),
}


@dataclass
class Rotation:
    interval: float = DEFAULT_ROTATE_SECONDS
    identity: str | None = None
    manual: bool = False
    revision: int | None = None
    due: float | None = None

    def update(self, report: dict[str, Any], now: float) -> dict[str, Any] | None:
        accounts = report["accounts"]
        intent = report.get("view")
        if intent and intent["revision"] != self.revision:
            self.revision = intent["revision"]
            self.manual = intent["mode"] == "hold"
            self.identity = intent.get("identity") if self.manual else self.identity
            self.due = now + self.interval
        if not accounts:
            return None
        ids = [a["identity"] for a in accounts]
        if self.identity not in ids:
            if self.manual:
                return None
            self.identity = ids[0]
            self.due = now + self.interval
        if self.due is None:
            self.due = now + self.interval
        if not self.manual and self.interval > 0 and now >= self.due:
            self.identity = ids[(ids.index(self.identity) + 1) % len(ids)]
            self.due = now + self.interval
        return accounts[ids.index(self.identity)]

    def key(self, key: str, report: dict[str, Any], now: float) -> None:
        accounts = report["accounts"]
        if key == "r":
            self.manual = False
            self.due = now + self.interval
            return
        if not accounts:
            return
        ids = [a["identity"] for a in accounts]
        index = ids.index(self.identity) if self.identity in ids else 0
        if key in {"next", "previous"}:
            index = (index + (1 if key == "next" else -1)) % len(ids)
        elif len(key) == 1 and key in "0123456789":
            index = 9 if key == "0" else int(key) - 1
            if index >= len(ids):
                return
        else:
            return
        self.identity = ids[index]
        self.manual = True
        self.due = now + self.interval


def binding(account: dict[str, Any], now: float) -> tuple[dict[str, Any] | None, str]:
    """Only show current known numeric evidence; unknown relationships stay explicit."""
    freshness = account.get("freshness", "unknown")
    if freshness != "fresh":
        return None, freshness.upper()
    if account.get("usageStatus") not in {"ok", "fresh"}:
        return None, "UNKNOWN"
    windows = account.get("windows", [])
    if account.get("source") == "quota-axi":
        semantics = account.get("quotaSemantics")
        if not isinstance(semantics, dict):
            return None, "UNKNOWN BOUNDS"
        scopes = semantics.get("effectiveAvailability", [])
        if (
            semantics.get("status") != "known"
            or not isinstance(scopes, list)
            or not scopes
            or any(
                not isinstance(scope, dict)
                or scope.get("status") != "known"
                or scope.get("boundConflict")
                or not isinstance(scope.get("boundedBy"), list)
                or any(not isinstance(bound, str) for bound in scope["boundedBy"])
                for scope in scopes
            )
        ):
            return None, "UNKNOWN BOUNDS"
        bound_ids = {wid for scope in scopes for wid in scope.get("boundedBy", [])}
        if not bound_ids or not bound_ids.issubset({w["scope"] for w in windows}):
            return None, "UNKNOWN BOUNDS"
        windows = [w for w in windows if w["scope"] in bound_ids]
    if not windows:
        return None, "UNKNOWN"
    for window in windows:
        value = window.get("percentRemaining")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, "UNKNOWN"
        if not math.isfinite(value) or not 0 <= value <= 100:
            return None, "UNKNOWN"
        reset = window.get("resetsAt")
        stamp = parse_time(reset)
        if reset is not None and (stamp is None or stamp <= now):
            return None, "UNKNOWN RESET"
    return min(windows, key=lambda w: (w["percentRemaining"], w["scope"])), "FRESH"


def countdown(value: str | None, now: float) -> str:
    stamp = parse_time(value)
    if stamp is None:
        return "UNKNOWN"
    seconds = max(0, int(stamp - now))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def card(
    report: dict[str, Any],
    account: dict[str, Any] | None,
    width: int,
    height: int,
    held: bool,
    now: float,
) -> list[str]:
    if width <= 0 or height <= 0:
        return []
    if width < 20 or height < 3:
        return [fit_text("Need 20x3", width)]
    accounts = report["accounts"]
    if account is None:
        message = "Selected account unavailable" if held else "No account evidence"
        return [fit_text(message, width), fit_text(f"{len(accounts)} accounts; r: rotate", width)]
    index = next(i for i, a in enumerate(accounts) if a["identity"] == account["identity"])
    window, status = binding(account, now)
    pct = math.floor(window["percentRemaining"]) if window else None
    label = f"{account['label']} | {account['provider']}"
    mode = "HOLD" if held else "AUTO"
    footer = f"account {index + 1} of {len(accounts)} {mode}"
    scope = window["scope"] if window else status
    reset = countdown(window.get("resetsAt"), now) if window else "UNKNOWN"
    if height < 9:
        rows = [
            label,
            f"REMAIN {'?' if pct is None else pct}% | {status}",
            f"LIMIT {scope}",
            f"RESETS IN {reset}",
            footer,
        ]
        if height < len(rows):
            rows = rows[: height - 1] + [footer]
        return [fit_text(row, width) for row in rows]
    filled = 0 if pct is None else width * pct // 100
    bar = "░" * width if pct is None else "█" * filled + "░" * (width - filled)
    text = "?" if pct is None else f"{pct}%"
    digits = [" ".join(GLYPHS[c][row] for c in text) for row in range(3)]
    # Stretch horizontally when room permits; three terminal rows remain dedicated to digits.
    if max(len(row) for row in digits) * 2 <= width:
        digits = ["".join(c * 2 for c in row) for row in digits]
    lines = [label, bar, bar, *digits, f"LIMIT {scope} | {status}", f"RESETS IN {reset}", footer]
    return [fit_text(line, width) for line in lines]
