from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unicodedata import category

from wcwidth import wcswidth


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
    accounts = report["accounts"]
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
