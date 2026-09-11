from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from quartermaster.core import QuartermasterError, Store, advise, ingest, reconcile, view
from quartermaster.render import render

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


def fresh_store(tmp_path: Path) -> Store:
    store = Store(tmp_path)
    ingest(store, "cswap", load("cswap.json"), "fixture", "2099-01-01T00:00:01Z")
    return store


def test_two_accounts_distinct_and_windows_are_remaining(tmp_path):
    report = view(fresh_store(tmp_path).read(), now=4070908801)
    assert [a["label"] for a in report["accounts"]] == ["P20x", "O5x"]
    assert len({a["identity"] for a in report["accounts"]}) == 2
    assert report["accounts"][0]["windows"][0]["percentRemaining"] == 42


def test_malformed_ingest_does_not_replace_last_good(tmp_path):
    store = fresh_store(tmp_path)
    before = store.path.read_bytes()
    with pytest.raises(QuartermasterError):
        ingest(store, "cswap", {"schemaVersion": 1, "accounts": "bad"}, "fixture")
    assert store.path.read_bytes() == before


def test_quota_axi_preserves_other_source_and_rejects_claude(tmp_path):
    store = fresh_store(tmp_path)
    ingest(store, "quota-axi", load("quota-axi.json"), "fixture", "2099-01-01T00:00:02Z")
    assert len(view(store.read(), now=4070908801)["accounts"]) == 3
    bad = load("quota-axi.json")
    bad["providers"][0]["provider"] = "claude"
    with pytest.raises(QuartermasterError, match="prohibited"):
        ingest(store, "quota-axi", bad, "fixture")


def test_stale_and_unknown_are_explicit(tmp_path):
    report = view(fresh_store(tmp_path).read(), now=4070910000, freshness_seconds=300)
    assert {a["freshness"] for a in report["accounts"]} == {"stale"}
    state = fresh_store(tmp_path).read()
    state["sources"]["cswap:fixture"]["accounts"][0]["measurementAt"] = None
    assert view(state, now=4070908801)["accounts"][0]["freshness"] == "unknown"


def test_weekly_exhaustion_is_red_even_when_five_hour_is_fresh(tmp_path):
    store = fresh_store(tmp_path)
    with store.locked() as state:
        state["sources"]["cswap:fixture"]["accounts"][0]["windows"][1]["percentRemaining"] = 0
        store.write(state)
    result = advise(store, "r1", "claude", None, {"demandEvidence": True}, now=4070908801)
    assert result["accountLabel"] == "O5x"


def test_missing_demand_is_yellow_and_retry_is_stable(tmp_path):
    store = fresh_store(tmp_path)
    first = advise(store, "r1", "claude", None, {}, now=4070908801)
    second = advise(store, "r1", "claude", None, {}, now=4070908801)
    assert first["decision"] == "YELLOW"
    assert second["replayed"] is True
    with pytest.raises(QuartermasterError, match="changed content"):
        advise(store, "r1", "claude", "other", {}, now=4070908801)


def test_rate_uses_distinct_samples_and_invalidates_reset_change(tmp_path):
    store = fresh_store(tmp_path)
    newer = load("cswap.json")
    newer["accounts"] = newer["accounts"][:1]
    newer["accounts"][0]["usageFetchedAt"] = "2099-01-01T00:01:00Z"
    newer["accounts"][0]["usage"]["fiveHour"]["pct"] = 59
    ingest(store, "cswap", newer, "fixture", "2099-01-01T00:01:01Z")
    result = advise(store, "rate", "claude", None, {"demandEvidence": True}, now=4070908861)
    assert result["rateEvidence"]["status"] == "known"
    changed = load("cswap.json")
    changed["accounts"] = changed["accounts"][:1]
    changed["accounts"][0]["usageFetchedAt"] = "2099-01-01T00:02:00Z"
    changed["accounts"][0]["usage"]["fiveHour"]["resetsAt"] = "2099-01-02T01:12:00Z"
    ingest(store, "cswap", changed, "fixture", "2099-01-01T00:02:01Z")
    result = advise(store, "changed", "claude", None, {"demandEvidence": True}, now=4070908921)
    assert result["rateEvidence"]["status"] == "known"
    assert {w["scope"] for w in result["rateEvidence"]["windows"]} == {"seven_day"}


def test_rate_projection_starts_at_current_measurement(tmp_path):
    store = fresh_store(tmp_path)
    previous = load("cswap.json")
    previous["accounts"] = previous["accounts"][:1]
    previous["accounts"][0]["usage"]["fiveHour"]["pct"] = 49
    previous["accounts"][0]["usage"]["fiveHour"]["resetsAt"] = "2099-01-01T00:41:00Z"
    ingest(store, "cswap", previous, "fixture", "2099-01-01T00:00:01Z")
    current = load("cswap.json")
    current["accounts"] = current["accounts"][:1]
    current["accounts"][0]["usageFetchedAt"] = "2099-01-01T00:01:00Z"
    current["accounts"][0]["usage"]["fiveHour"]["pct"] = 50
    current["accounts"][0]["usage"]["fiveHour"]["resetsAt"] = "2099-01-01T00:41:00Z"
    ingest(store, "cswap", current, "fixture", "2099-01-01T00:01:01Z")

    result = advise(store, "rate-origin", "claude", None, {"demandEvidence": True}, now=4070908980)

    five_hour = next(w for w in result["rateEvidence"]["windows"] if w["scope"] == "five_hour")
    assert five_hour["projectedRemainingAtReset"] == pytest.approx(10)
    assert result["decision"] == "YELLOW"


def _consult(path: str, request_id: str, queue):
    queue.put(
        advise(
            Store(Path(path), lock_timeout=5),
            request_id,
            "claude",
            None,
            {"demandEvidence": True},
            now=4070908801,
        )
    )


def test_concurrent_advice_allows_only_one_green(tmp_path):
    fresh_store(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    processes = [
        ctx.Process(target=_consult, args=(str(tmp_path), f"r{i}", queue)) for i in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    results = [queue.get(timeout=1), queue.get(timeout=1)]
    assert sum(r["decision"] == "GREEN" for r in results) == 2  # distinct accounts
    third = advise(Store(tmp_path), "r3", "claude", None, {"demandEvidence": True}, now=4070908801)
    assert third["decision"] == "YELLOW"


def test_reconciliation_preserves_demand_semantics(tmp_path):
    store = fresh_store(tmp_path)
    advise(store, "r1", "claude", None, {"demandEvidence": True}, now=4070908801)
    assert reconcile(store, "r1", "launch", "pid:123")["status"] == "active"
    replay = advise(store, "r1", "claude", None, {"demandEvidence": True}, now=4070908801)
    assert replay["status"] == "active"
    assert reconcile(store, "r1", "complete")["status"] == "completed"


def test_32_by_6_and_tiny_rendering(tmp_path):
    report = view(fresh_store(tmp_path).read(), now=4070908801)
    lines = render(report, 32, 6)
    assert len(lines) == 6 and all(len(line) <= 32 for line in lines)
    assert any("P20x" in line for line in lines) and any("O5x" in line for line in lines)
    assert "Need 20x3" in render(report, 10, 2)[0]
