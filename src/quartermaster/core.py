from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_FRESHNESS_SECONDS = 300


class QuartermasterError(Exception):
    pass


class BusyError(QuartermasterError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def default_state() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "sources": {}, "requests": {}}


class Store:
    def __init__(self, directory: Path, lock_timeout: float = 2.0):
        self.directory = directory
        self.path = directory / "state.json"
        self.lock_path = directory / "state.lock"
        self.lock_timeout = lock_timeout

    @contextmanager
    def locked(self) -> Iterator[dict[str, Any]]:
        import fcntl

        self.directory.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise BusyError("state lock is busy")
                    time.sleep(0.02)
            state = self.read()
            try:
                yield state
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return default_state()
        try:
            value = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise QuartermasterError(f"cannot read state: {exc}") from exc
        if value.get("schemaVersion") != SCHEMA_VERSION:
            raise QuartermasterError("unsupported Quartermaster state schema")
        return value

    def write(self, state: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="state-", suffix=".json", dir=self.directory)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def _window(scope: str, raw: dict[str, Any], source: str) -> dict[str, Any]:
    pct = raw.get("percentRemaining")
    if pct is None and isinstance(raw.get("pct"), (int, float)):
        pct = 100 - raw["pct"]
    if pct is not None and (not isinstance(pct, (int, float)) or not 0 <= pct <= 100):
        raise QuartermasterError(f"invalid percentage for {scope}")
    return {
        "scope": scope,
        "percentRemaining": pct,
        "resetsAt": raw.get("resetsAt"),
        "source": source,
    }


def normalize_cswap(data: Any, host: str, collected_at: str) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise QuartermasterError("expected cswap schemaVersion 1")
    rows = data.get("accounts")
    if not isinstance(rows, list):
        raise QuartermasterError("cswap document must contain accounts[]")
    accounts = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise QuartermasterError("invalid cswap account row")
        number, email, org = row.get("number"), row.get("email"), row.get("organizationUuid", "")
        identity = f"{host}|{number}|{email}|{org}"
        if identity in seen:
            raise QuartermasterError("duplicate cswap account identity")
        seen.add(identity)
        label = row.get("alias") or f"slot-{number}"
        status = row.get("usageStatus", "unavailable")
        current = row.get("usage") if status == "ok" else None
        measurement = row.get("usageFetchedAt")
        windows = []
        if isinstance(current, dict):
            for key, scope in (("fiveHour", "five_hour"), ("sevenDay", "seven_day")):
                if isinstance(current.get(key), dict):
                    windows.append(_window(scope, current[key], "cswap"))
            for scoped in current.get("scoped", []):
                if isinstance(scoped, dict):
                    windows.append(_window(f"model:{scoped.get('name', 'unknown')}", scoped, "cswap"))
        accounts.append({
            "provider": "claude", "source": "cswap", "host": host,
            "identity": hashlib.sha256(identity.encode()).hexdigest()[:20],
            "label": str(label), "selector": number, "usageStatus": status,
            "measurementAt": measurement, "collectedAt": collected_at,
            "windows": windows,
            "lastGood": {"measurementAt": row.get("lastGoodFetchedAt"), "available": bool(row.get("lastGoodUsage"))},
        })
    return {"kind": "cswap", "upstreamSchemaVersion": 1, "host": host,
            "collectedAt": collected_at, "accounts": accounts}


def normalize_quota_axi(data: Any, host: str, collected_at: str) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("schemaVersion") != 5:
        raise QuartermasterError("expected quota-axi schemaVersion 5")
    providers = data.get("providers")
    if not isinstance(providers, list):
        raise QuartermasterError("quota-axi document must contain providers[]")
    accounts = []
    for provider in providers:
        if not isinstance(provider, dict):
            raise QuartermasterError("invalid quota-axi provider row")
        name = provider.get("provider")
        if name == "claude":
            raise QuartermasterError("quota-axi Claude rows are prohibited; use cswap")
        state = provider.get("state") or {}
        raw_account = provider.get("account") or {}
        identity_raw = f"{host}|{name}|{raw_account.get('accountId','')}|{raw_account.get('email','')}"
        windows = [_window(str(w.get("id", "unknown")), w, "quota-axi")
                   for w in provider.get("windows", []) if isinstance(w, dict)]
        accounts.append({
            "provider": name, "source": "quota-axi", "host": host,
            "identity": hashlib.sha256(identity_raw.encode()).hexdigest()[:20],
            "label": str(provider.get("plan") or name), "selector": None,
            "usageStatus": state.get("status", "unavailable"),
            "measurementAt": state.get("refreshedAt") or data.get("generatedAt"),
            "collectedAt": collected_at, "windows": windows,
            "staleReported": bool(state.get("stale")), "quotaSemantics": provider.get("quotaSemantics"),
        })
    return {"kind": "quota-axi", "upstreamSchemaVersion": 5, "host": host,
            "collectedAt": collected_at, "accounts": accounts}


def ingest(store: Store, kind: str, data: Any, host: str, now: str | None = None) -> dict[str, Any]:
    collected_at = now or utc_now()
    normalized = (normalize_cswap if kind == "cswap" else normalize_quota_axi)(data, host, collected_at)
    key = f"{kind}:{host}"
    with store.locked() as state:
        state["sources"][key] = normalized
        store.write(state)
    return normalized


def view(state: dict[str, Any], now: float | None = None,
         freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS) -> dict[str, Any]:
    clock = now if now is not None else time.time()
    accounts = []
    for source in state["sources"].values():
        for account in source["accounts"]:
            item = dict(account)
            measured = parse_time(item.get("measurementAt"))
            age = None if measured is None else max(0, clock - measured)
            item["ageSeconds"] = None if age is None else round(age, 1)
            item["freshness"] = "unknown" if age is None else ("fresh" if age <= freshness_seconds else "stale")
            if item.get("staleReported"):
                item["freshness"] = "stale"
            accounts.append(item)
    return {"schemaVersion": SCHEMA_VERSION, "displayedAt": utc_now(), "freshnessSeconds": freshness_seconds,
            "accounts": accounts, "requests": list(state["requests"].values()),
            "view": state.get("view")}


def select_view(store: Store, selector: str) -> dict[str, Any]:
    """Persist display-only intent in the same transaction as all other state writers."""
    with store.locked() as state:
        selection = {"mode": "auto", "identity": None}
        if selector != "auto":
            accounts = view(state)["accounts"]
            kind, separator, value = selector.partition(":")
            if separator and kind in {"index", "identity", "label"}:
                if kind == "index":
                    if not value.isascii() or not value.isdigit():
                        matches = []
                    else:
                        index = int(value) - 1
                        matches = accounts[index:index + 1] if index >= 0 else []
                elif kind == "identity":
                    matches = [a for a in accounts if a["identity"] == value]
                else:
                    matches = [a for a in accounts if a["label"] == value]
            else:
                matches = [a for a in accounts if a["identity"] == selector]
                matches.extend(a for a in accounts if a["label"] == selector)
                if selector.isascii() and selector.isdigit():
                    index = int(selector) - 1
                    if index >= 0:
                        matches.extend(accounts[index:index + 1])
            identities = {match["identity"] for match in matches}
            if len(identities) != 1:
                raise QuartermasterError(
                    "selector must resolve to one account; use index:, identity:, or label: to disambiguate"
                )
            selection = {"mode": "hold", "identity": identities.pop()}
        selection["revision"] = (state.get("view") or {}).get("revision", 0) + 1
        state["view"] = selection
        store.write(state)
        return selection


def request_fingerprint(provider: str, model: str | None, metadata: dict[str, Any]) -> str:
    raw = json.dumps({"provider": provider, "model": model, "metadata": metadata}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def advise(store: Store, request_id: str, provider: str, model: str | None,
           metadata: dict[str, Any], reserve: float = 10, now: float | None = None) -> dict[str, Any]:
    clock = now if now is not None else time.time()
    fingerprint = request_fingerprint(provider, model, metadata)
    with store.locked() as state:
        existing = state["requests"].get(request_id)
        if existing:
            if existing["fingerprint"] != fingerprint:
                raise QuartermasterError("request ID reused with changed content")
            result = dict(existing)
            result["replayed"] = True
            if result["status"] == "pending" and result["decision"] == "GREEN":
                result["validity"] = "recorded_pending_not_new_green"
            return result
        report = view(state, clock)
        eligible = [a for a in report["accounts"] if a["provider"] == provider]
        decisions = []
        for account in eligible:
            windows = account.get("windows", [])
            pcts = [w["percentRemaining"] for w in windows if w.get("percentRemaining") is not None]
            if account["freshness"] != "fresh" or not windows or len(pcts) != len(windows):
                grade, reason = "UNKNOWN", "missing or stale current evidence"
            elif min(pcts) <= 0:
                grade, reason = "RED", "a limiting window is exhausted"
            elif min(pcts) <= reserve:
                grade, reason = "YELLOW", f"headroom is at or below {reserve:g}-point reserve"
            else:
                pending_green = any(r.get("accountIdentity") == account["identity"] and
                                    r.get("status") in {"pending", "active"} and r.get("decision") == "GREEN"
                                    for r in state["requests"].values())
                if pending_green:
                    grade, reason = "YELLOW", "account already has unresolved green demand"
                elif not metadata.get("demandEvidence"):
                    grade, reason = "YELLOW", "quota is healthy but demand evidence is missing"
                else:
                    grade, reason = "GREEN", "fresh windows preserve reserve with demand evidence"
            decisions.append((grade, min(pcts) if pcts else -1, account, reason))
        rank = {"GREEN": 3, "YELLOW": 2, "UNKNOWN": 1, "RED": 0}
        if decisions:
            grade, _, account, reason = max(decisions, key=lambda x: (rank[x[0]], x[1], x[2]["identity"]))
            identity, label = account["identity"], account["label"]
        else:
            grade, reason, identity, label = "UNKNOWN", "no eligible account evidence", None, None
        record = {"requestId": request_id, "fingerprint": fingerprint, "provider": provider,
                  "model": model, "decision": grade, "reason": reason, "accountIdentity": identity,
                  "accountLabel": label, "status": "pending", "createdAt": utc_now(),
                  "metadata": metadata, "validity": "recorded"}
        state["requests"][request_id] = record
        store.write(state)
        return record


def reconcile(store: Store, request_id: str, event: str, process_id: str | None = None) -> dict[str, Any]:
    with store.locked() as state:
        record = state["requests"].get(request_id)
        if not record:
            raise QuartermasterError("unknown request ID")
        transitions = {"cancel": {"pending", "active"}, "launch": {"pending"}, "complete": {"active"}}
        if event not in transitions or record["status"] not in transitions[event]:
            raise QuartermasterError(f"invalid {event} transition from {record['status']}")
        if event == "launch" and not process_id:
            raise QuartermasterError("launch reconciliation requires --process-id")
        record["status"] = {"cancel": "cancelled", "launch": "active", "complete": "completed"}[event]
        record["reconciledAt"] = utc_now()
        if process_id:
            record["processId"] = process_id
        store.write(state)
        return dict(record)
