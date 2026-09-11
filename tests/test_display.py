import copy
import json
import multiprocessing

import pytest
from wcwidth import wcswidth

from quartermaster.cli import main
from quartermaster.core import QuartermasterError, Store, ingest, select_view, view
from quartermaster.display import Rotation, binding, card

NOW = 1789128000.0
MISSING = object()


def fleet(count=11):
    return {
        "accounts": [
            {
                "identity": f"identity-{i}",
                "label": f"account-{i}",
                "provider": "claude",
                "source": "cswap",
                "freshness": "fresh",
                "usageStatus": "ok",
                "windows": [
                    {
                        "scope": "five_hour",
                        "percentRemaining": 80,
                        "resetsAt": "2026-09-12T12:00:00Z",
                    },
                    {
                        "scope": "seven_day",
                        "percentRemaining": 25,
                        "resetsAt": "2026-09-15T12:00:00Z",
                    },
                ],
            }
            for i in range(1, count + 1)
        ]
    }


def ingested_report(tmp_path, kind, reset=MISSING):
    window = {"id": "five_hour", "percentRemaining": 25}
    if reset is not MISSING:
        window["resetsAt"] = reset
    measured = "2026-09-11T12:00:00Z"
    if kind == "cswap":
        document = {
            "schemaVersion": 1,
            "accounts": [
                {
                    "number": 1,
                    "email": "account@example.invalid",
                    "usageStatus": "ok",
                    "usageFetchedAt": measured,
                    "usage": {"fiveHour": window},
                }
            ],
        }
    else:
        document = {
            "schemaVersion": 5,
            "providers": [
                {
                    "provider": "example",
                    "state": {"status": "fresh", "refreshedAt": measured},
                    "windows": [window],
                    "quotaSemantics": {
                        "status": "known",
                        "effectiveAvailability": [
                            {
                                "status": "known",
                                "boundedBy": ["five_hour"],
                            }
                        ],
                    },
                }
            ],
        }
    store = Store(tmp_path)
    ingest(store, kind, document, "fixture", now=measured)
    return view(store.read(), now=NOW)


def test_card_geometry_bar_and_binding_reset():
    report = fleet()
    lines = card(report, report["accounts"][1], 44, 9, False, NOW)
    assert len(lines) == 9
    assert all(0 <= wcswidth(line) <= 44 for line in lines)
    assert lines[1] == lines[2] == "█" * 11 + "░" * 33
    assert "seven_day" in lines[6]
    assert lines[7] == "RESETS IN 4d 0h"
    assert lines[8] == "account 2 of 11 AUTO"


@pytest.mark.parametrize("freshness", ["stale", "unknown"])
def test_stale_and_unknown_do_not_show_current_headroom(freshness):
    report = fleet(1)
    account = report["accounts"][0]
    account["freshness"] = freshness
    lines = card(report, account, 44, 9, False, NOW)
    assert lines[1] == "░" * 44
    assert freshness.upper() in lines[6]
    assert lines[7] == "RESETS IN UNKNOWN"


def test_model_limit_and_zero_are_not_hidden_by_session():
    report = fleet(1)
    account = report["accounts"][0]
    account["windows"].append(
        {"scope": "model:example", "percentRemaining": 0, "resetsAt": "2026-09-16T12:00:00Z"}
    )
    window, status = binding(account, NOW)
    assert status == "FRESH" and window["scope"] == "model:example"
    lines = card(report, account, 44, 9, False, NOW)
    assert lines[1] == "░" * 44
    assert "model:example" in lines[6]


def test_quota_axi_uses_only_explicit_bounds():
    account = fleet(1)["accounts"][0]
    account["source"] = "quota-axi"
    account["usageStatus"] = "fresh"
    assert binding(account, NOW)[0] is None
    account["quotaSemantics"] = {
        "status": "known",
        "effectiveAvailability": [
            {"status": "known", "scope": "all_models", "boundedBy": ["five_hour"]}
        ],
    }
    assert binding(account, NOW)[0]["scope"] == "five_hour"
    account["quotaSemantics"]["effectiveAvailability"][0]["boundConflict"] = {"a": 1}
    assert binding(account, NOW)[0] is None


@pytest.mark.parametrize(
    "semantics",
    [
        "known",
        [],
        {"status": "known", "effectiveAvailability": "five_hour"},
        {"status": "known", "effectiveAvailability": ["five_hour"]},
        {
            "status": "known",
            "effectiveAvailability": [{"status": "known", "boundedBy": "five_hour"}],
        },
        {
            "status": "known",
            "effectiveAvailability": [{"status": "known", "boundedBy": [{}]}],
        },
    ],
)
def test_malformed_quota_semantics_fail_closed(semantics):
    report = fleet(1)
    account = report["accounts"][0]
    account["source"] = "quota-axi"
    account["usageStatus"] = "fresh"
    account["quotaSemantics"] = semantics
    assert binding(account, NOW) == (None, "UNKNOWN BOUNDS")
    assert "UNKNOWN BOUNDS" in card(report, account, 44, 9, False, NOW)[6]


def test_expired_reset_and_missing_values_are_unknown():
    account = fleet(1)["accounts"][0]
    account["windows"][0]["percentRemaining"] = None
    assert binding(account, NOW)[0] is None
    account["windows"][0]["percentRemaining"] = 80
    account["windows"][0]["resetsAt"] = "2020-01-01T00:00:00Z"
    assert binding(account, NOW)[0] is None


@pytest.mark.parametrize("kind", ["cswap", "quota-axi"])
@pytest.mark.parametrize("include_null", [False, True])
def test_ingested_missing_reset_does_not_show_headroom(tmp_path, kind, include_null):
    reset = None if include_null else MISSING
    report = ingested_report(tmp_path, kind, reset)
    account = report["accounts"][0]
    assert account["freshness"] == "fresh"
    assert binding(account, NOW) == (None, "UNKNOWN RESET")
    lines = card(report, account, 44, 9, False, NOW)
    assert lines[1] == lines[2] == "░" * 44
    assert lines[7] == "RESETS IN UNKNOWN"
    assert card(report, account, 32, 6, False, NOW)[1] == "REMAIN ?% | UNKNOWN RESET"


@pytest.mark.parametrize("kind", ["cswap", "quota-axi"])
def test_ingested_timezone_naive_reset_does_not_show_headroom(tmp_path, kind):
    report = ingested_report(tmp_path, kind, "2026-09-12T12:00:00")
    account = report["accounts"][0]
    assert binding(account, NOW) == (None, "UNKNOWN RESET")
    lines = card(report, account, 44, 9, False, NOW)
    assert lines[1] == lines[2] == "░" * 44
    assert lines[7] == "RESETS IN UNKNOWN"


@pytest.mark.parametrize("kind", ["cswap", "quota-axi"])
@pytest.mark.parametrize(
    "reset",
    ["2026-09-12T12:00:00Z", "2026-09-12T05:00:00-07:00"],
)
def test_ingested_explicit_offset_reset_shows_headroom(tmp_path, kind, reset):
    report = ingested_report(tmp_path, kind, reset)
    account = report["accounts"][0]
    window, status = binding(account, NOW)
    assert status == "FRESH"
    assert window is not None and window["percentRemaining"] == 25
    lines = card(report, account, 44, 9, False, NOW)
    assert lines[1] == lines[2] == "█" * 11 + "░" * 33
    assert lines[7] == "RESETS IN 24h 0m"


def test_all_eleven_accounts_rotate_in_under_a_minute():
    report = fleet()
    rotation = Rotation()
    seen = [rotation.update(report, t)["identity"] for t in range(0, 55, 5)]
    assert len(set(seen)) == 11
    assert rotation.update(report, 55)["identity"] == seen[0]


def test_redraw_does_not_advance_rotation_and_hotkeys_hold():
    report = fleet()
    rotation = Rotation()
    assert rotation.update(report, 0)["identity"] == "identity-1"
    assert rotation.update(report, 4.9)["identity"] == "identity-1"
    rotation.key("2", report, 4.9)
    assert rotation.update(report, 99)["identity"] == "identity-2"
    rotation.key("previous", report, 99)
    assert rotation.update(report, 100)["identity"] == "identity-1"
    rotation.key("0", report, 100)
    assert rotation.update(report, 101)["identity"] == "identity-10"
    rotation.key("next", report, 101)
    assert rotation.update(report, 102)["identity"] == "identity-11"
    rotation.key("r", report, 102)
    assert rotation.update(report, 107)["identity"] == "identity-1"


def test_rotate_zero_holds_but_allows_navigation():
    report = fleet()
    rotation = Rotation(0)
    rotation.update(report, 0)
    assert rotation.update(report, 999)["identity"] == "identity-1"
    rotation.key("next", report, 999)
    assert rotation.update(report, 1000)["identity"] == "identity-2"


def test_selection_survives_reordering_and_missing_account_stays_explicit():
    report = fleet()
    report["view"] = {"mode": "hold", "identity": "identity-3", "revision": 1}
    rotation = Rotation()
    assert rotation.update(report, 0)["identity"] == "identity-3"
    report["accounts"].reverse()
    assert rotation.update(report, 99)["identity"] == "identity-3"
    report["accounts"] = [a for a in report["accounts"] if a["identity"] != "identity-3"]
    assert rotation.update(report, 100) is None
    assert "unavailable" in card(report, None, 44, 9, True, NOW)[0]
    report["view"] = {"mode": "auto", "identity": None, "revision": 2}
    assert rotation.update(report, 101) is not None


def test_new_remote_revision_overrides_local_hold():
    report = fleet()
    report["view"] = {"mode": "hold", "identity": "identity-2", "revision": 1}
    rotation = Rotation()
    rotation.update(report, 0)
    rotation.key("3", report, 1)
    assert rotation.update(report, 2)["identity"] == "identity-3"
    report["view"]["revision"] = 2
    assert rotation.update(report, 3)["identity"] == "identity-2"


@pytest.mark.parametrize("size", [(44, 9), (32, 6), (20, 3), (7, 1), (0, 0)])
def test_safe_text_and_small_frames(size):
    report = fleet(1)
    report["accounts"][0]["label"] = "\x1b[2J\n账户" * 50
    lines = card(report, report["accounts"][0], *size, False, NOW)
    assert len(lines) <= size[1]
    assert all(0 <= wcswidth(line) <= size[0] for line in lines)
    assert all("\x1b" not in line and "\n" not in line for line in lines)


def test_view_command_preserves_sources_and_ledger(tmp_path, capsys):
    store = Store(tmp_path)
    with store.locked() as state:
        state["sources"] = {"fixture": {"accounts": fleet(2)["accounts"]}}
        state["requests"] = {"pending": {"status": "pending"}}
        store.write(state)
    before = copy.deepcopy(store.read())
    assert main(["--state-dir", str(tmp_path), "view", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["identity"] == "identity-2"
    after = store.read()
    assert after["sources"] == before["sources"]
    assert after["requests"] == before["requests"]
    assert view(after)["view"]["revision"] == 1
    assert select_view(store, "account-1")["identity"] == "identity-1"
    assert select_view(store, "identity-2")["identity"] == "identity-2"
    assert select_view(store, "auto")["mode"] == "auto"
    snapshot = store.path.read_bytes()
    with pytest.raises(QuartermasterError):
        select_view(store, "99")
    assert store.path.read_bytes() == snapshot
    ingest(store, "cswap", {"schemaVersion": 1, "accounts": []}, "fixture")
    assert store.read()["view"] == after["view"] | {"identity": None, "mode": "auto", "revision": 4}


def test_view_selector_requires_disambiguation_when_forms_overlap(tmp_path):
    store = Store(tmp_path)
    accounts = fleet(2)["accounts"]
    accounts[0]["identity"] = "2"
    accounts[0]["label"] = "auto"
    accounts[1]["label"] = "2"
    with store.locked() as state:
        state["sources"] = {"fixture": {"accounts": accounts}}
        store.write(state)

    before = store.path.read_bytes()
    with pytest.raises(QuartermasterError):
        select_view(store, "2")
    assert store.path.read_bytes() == before
    assert select_view(store, "identity:2")["identity"] == "2"
    assert select_view(store, "label:2")["identity"] == "identity-2"
    assert select_view(store, "index:2")["identity"] == "identity-2"
    assert select_view(store, "label:auto")["identity"] == "2"
    assert select_view(store, "auto")["mode"] == "auto"


@pytest.mark.parametrize(
    "flag,value",
    [("--rotate", "-1"), ("--rotate", "nan"), ("--refresh", "0"), ("--refresh", "inf")],
)
def test_invalid_timing_options_fail_without_hanging(tmp_path, capsys, flag, value):
    assert main(["--state-dir", str(tmp_path), "tui", "--once", flag, value]) == 1
    assert "UNKNOWN" in capsys.readouterr().err


def _concurrent_writer(directory, operation):
    from quartermaster.core import advise

    store = Store(directory, lock_timeout=5)
    if operation == "view":
        select_view(store, "identity-2")
    elif operation == "ingest":
        ingest(store, "cswap", {"schemaVersion": 1, "accounts": []}, "new-source")
    else:
        advise(store, "concurrent-request", "example", None, {})


def test_concurrent_view_ingest_and_advice_preserve_each_other(tmp_path):
    store = Store(tmp_path)
    with store.locked() as state:
        state["sources"] = {"fixture": {"accounts": fleet(2)["accounts"]}}
        store.write(state)
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_concurrent_writer, args=(tmp_path, operation))
        for operation in ("view", "ingest", "advise")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    state = store.read()
    assert state["view"]["identity"] == "identity-2"
    assert "cswap:new-source" in state["sources"]
    assert state["requests"]["concurrent-request"]["status"] == "pending"


def test_ambiguous_label_does_not_change_selection(tmp_path):
    store = Store(tmp_path)
    accounts = fleet(2)["accounts"]
    for account in accounts:
        account["label"] = "same-label"
    with store.locked() as state:
        state["sources"] = {"fixture": {"accounts": accounts}}
        store.write(state)
    before = store.path.read_bytes()
    with pytest.raises(QuartermasterError):
        select_view(store, "same-label")
    assert store.path.read_bytes() == before
