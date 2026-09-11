from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any
from unicodedata import category

from wcwidth import wcswidth


def evidence_time(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.timestamp()


def _percentage(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and 0 <= value <= 100
        and math.isfinite(value)
    )


def binding(account: dict[str, Any], now: float) -> tuple[dict[str, Any] | None, str]:
    """Only show current known numeric evidence; unknown relationships stay explicit."""
    freshness = account.get("freshness", "unknown")
    if freshness != "fresh":
        return None, freshness.upper()
    if evidence_time(account.get("measurementAt")) is None:
        return None, "UNKNOWN MEASUREMENT"
    if account.get("usageStatus") not in {"ok", "fresh"}:
        return None, "UNKNOWN"
    windows = account.get("windows", [])
    if not isinstance(windows, list) or not windows:
        return None, "UNKNOWN"
    if any(
        not isinstance(window, dict)
        or not isinstance(window.get("scope"), str)
        or not window["scope"]
        for window in windows
    ):
        return None, "UNKNOWN"
    scopes = []
    if account.get("source") == "quota-axi":
        semantics = account.get("quotaSemantics")
        if not isinstance(semantics, dict):
            return None, "UNKNOWN BOUNDS"
        scopes = semantics.get("effectiveAvailability", [])
        if (
            semantics.get("status") != "known"
            or semantics.get("unresolvedWindowIds", []) != []
            or not isinstance(scopes, list)
            or not scopes
            or any(
                not isinstance(scope, dict)
                or scope.get("status") != "known"
                or not isinstance(scope.get("scope"), str)
                or not scope["scope"]
                or "boundConflict" in scope
                or not isinstance(scope.get("boundedBy"), list)
                or not scope["boundedBy"]
                or any(not isinstance(bound, str) or not bound for bound in scope["boundedBy"])
                or len(set(scope["boundedBy"])) != len(scope["boundedBy"])
                or not isinstance(scope.get("limitingWindowIds"), list)
                or not scope["limitingWindowIds"]
                or any(
                    not isinstance(window_id, str) or not window_id
                    for window_id in scope["limitingWindowIds"]
                )
                or len(set(scope["limitingWindowIds"])) != len(scope["limitingWindowIds"])
                or not _percentage(scope.get("effectivePercentRemaining"))
                for scope in scopes
            )
        ):
            return None, "UNKNOWN BOUNDS"
        if len({scope["scope"] for scope in scopes}) != len(scopes):
            return None, "UNKNOWN BOUNDS"
        bound_ids = {window_id for scope in scopes for window_id in scope["boundedBy"]}
        window_ids = {window["scope"] for window in windows}
        if len(window_ids) != len(windows) or bound_ids != window_ids:
            return None, "UNKNOWN BOUNDS"
    for window in windows:
        value = window.get("percentRemaining")
        if not _percentage(value):
            return None, "UNKNOWN"
        stamp = evidence_time(window.get("resetsAt"))
        if stamp is None or stamp <= now:
            return None, "UNKNOWN RESET"
    for scope in scopes:
        bounds = [window for window in windows if window["scope"] in scope["boundedBy"]]
        minimum = min(window["percentRemaining"] for window in bounds)
        expected = {
            window["scope"] for window in bounds if window["percentRemaining"] == minimum
        }
        reported = scope["limitingWindowIds"]
        if (
            scope["effectivePercentRemaining"] != minimum
            or set(reported) != expected
            or len(reported) != len(expected)
        ):
            return None, "UNKNOWN BOUNDS"
    return min(windows, key=lambda window: (window["percentRemaining"], window["scope"])), "FRESH"


def fit_text(text: str, width: int) -> str:
    """Make external text safe for a single terminal row and fit its cell budget."""
    if width <= 0:
        return ""
    text = "".join(
        "?" if category(c).startswith("C") and c not in {"\u200c", "\u200d"} else c
        for c in str(text)
    )
    if wcswidth(text) <= width:
        return text
    prefix = ""
    for character in text:
        if wcswidth(prefix + character) + 1 > width:
            break
        prefix += character
    return prefix + "~"


def _remaining(account: dict[str, Any], scope: str) -> str:
    values = [
        w.get("percentRemaining")
        for w in account.get("windows", [])
        if w.get("scope") == scope and w.get("percentRemaining") is not None
    ]
    return "?" if not values else str(round(min(values)))


def _reset(account: dict[str, Any]) -> str:
    candidates = [w for w in account.get("windows", []) if w.get("percentRemaining") is not None]
    if not candidates:
        return "?"
    value = min(candidates, key=lambda w: w["percentRemaining"]).get("resetsAt")
    if not value:
        return "?"
    try:
        target = datetime.fromisoformat(value)
        seconds = max(0, int((target - datetime.now(UTC)).total_seconds()))
        return f"{seconds // 3600:02}:{seconds % 3600 // 60:02}"
    except ValueError:
        return "?"


def _account_rows(labels: list[str], suffixes: list[str], width: int) -> list[str]:
    budget = max(1, width - max((wcswidth(suffix) for suffix in suffixes), default=0))
    rows = []
    for label, suffix in zip(labels, suffixes):
        label = fit_text(label, budget)
        label_width = wcswidth(label)
        rows.append(f"{label}{' ' * (budget - max(0, label_width))}{suffix}")
    return rows


def render(report: dict[str, Any], width: int, height: int) -> list[str]:
    accounts = []
    now = time.time()
    for account in report["accounts"]:
        if binding(account, now)[0] is None:
            account = {**account, "windows": []}
        accounts.append(account)
    if width < 20 or height < 3:
        return [f"Need 20x3 ({width}x{height})"][:height]
    if width < 32 or height < 6:
        visible = accounts[: max(1, height - 2)]
        lines = ["REMAIN 5h / 7d"]
        suffixes = [
            f" {_remaining(a, 'five_hour'):>3} / {_remaining(a, 'seven_day'):>3}%" for a in visible
        ]
        lines += _account_rows([a["label"] for a in visible], suffixes, width)
        hidden = len(accounts) - len(visible)
        lines.append((f"detail 1  +{hidden} hidden" if hidden else "detail 1  all shown")[:width])
        return lines[:height]
    claude = [a for a in accounts if a["provider"] == "claude"]
    visible = (claude + [a for a in accounts if a["provider"] != "claude"])[:2]
    lines = ["REMAIN 5h / 7d  reset5h"]
    suffixes = []
    for a in visible:
        mark = "!" if a["freshness"] != "fresh" else " "
        suffixes.append(
            f" {mark} {_remaining(a, 'five_hour'):>3} / {_remaining(a, 'seven_day'):>3}%  {_reset(a):>5}"
        )
    lines += _account_rows([a["label"] for a in visible], suffixes, width)
    age = max((a.get("ageSeconds") or 0 for a in visible), default=0)
    freshness = (
        "fresh" if visible and all(a["freshness"] == "fresh" for a in visible) else "stale/unknown"
    )
    lines.append(f"age {round(age / 60)}m  {freshness}"[:width])
    hidden = len(accounts) - len(visible)
    lines.append((f"details: +{hidden} hidden !" if hidden else "details: all accounts")[:width])
    lines.append("advice: run quartermaster advise"[:width])
    return lines[:height]
