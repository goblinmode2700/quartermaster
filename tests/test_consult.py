from __future__ import annotations

import json
import os
import pty
import select
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from quartermaster.cli import main
from quartermaster.consult import configuration
from quartermaster.core import QuartermasterError, Store, ingest, view

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fake(tmp_path):
    path = tmp_path / "fake claude"
    shutil.copyfile(FIXTURES / "fake_claude.py", path)
    path.chmod(0o700)
    return path


def cli(state, *args, **kwargs):
    return subprocess.run(
        [sys.executable, "-m", "quartermaster.cli", "--state-dir", str(state), *args],
        capture_output=True, timeout=15, check=False, **kwargs,
    )


def consultation(state):
    paths = list((state / "consultations").glob("consult-*"))
    assert len(paths) == 1
    return paths[0]


@pytest.mark.parametrize("kind,name", [("cswap", "cswap.json"), ("quota-axi", "quota-axi.json")])
def test_lossless_source_round_trip_and_projection(tmp_path, kind, name):
    document = json.loads((FIXTURES / name).read_text())
    document["future"] = {"unicode": "quota α", "nested": [None, True, 0, {"new": "value"}]}
    if kind == "cswap":
        window = document["accounts"][0]["usage"]["fiveHour"]
        document["accounts"][0]["lastGoodUsage"] = {"all": [1, 2, 3]}
    else:
        window = document["providers"][0]["windows"][0]
    window["pace"] = {"status": "fast", "burnMultiple": 2.5, "reservePercentPoints": -2}
    window["expectedPct"] = 12
    window["aheadOfPace"] = True
    window["willLastToReset"] = False
    store = Store(tmp_path)
    result = ingest(store, kind, document, "example")
    assert result["raw"] == document
    saved = store.read()
    assert saved["sources"][f"{kind}:example"]["raw"] == document
    report = view(saved)
    assert report["sources"][f"{kind}:example"]["raw"] == document
    assert report["accounts"][0]["windows"][0]["pace"] == window["pace"]
    # The stored snapshot must not alias a caller-owned object.
    document["future"]["nested"].append("later mutation")
    assert result["raw"] != document


def test_raw_replacement_preserves_other_sources_and_requests(tmp_path):
    store = Store(tmp_path)
    cswap = json.loads((FIXTURES / "cswap.json").read_text())
    other = json.loads((FIXTURES / "quota-axi.json").read_text())
    ingest(store, "cswap", cswap, "example")
    ingest(store, "quota-axi", other, "example")
    with store.locked() as state:
        state["requests"]["existing"] = {"status": "pending", "decision": "GREEN"}
        state["view"] = {"mode": "auto", "revision": 3}
        store.write(state)
    before = store.path.read_bytes()
    with pytest.raises(QuartermasterError):
        ingest(store, "cswap", {"schemaVersion": 1, "accounts": "invalid"}, "example")
    assert store.path.read_bytes() == before
    cswap["extension"] = [1, 2, 3]
    ingest(store, "cswap", cswap, "example")
    result = store.read()
    assert result["sources"]["cswap:example"]["raw"] == cswap
    assert result["sources"]["quota-axi:example"]["raw"] == other
    assert result["requests"]["existing"]["status"] == "pending"
    assert result["view"]["revision"] == 3


def test_defaults_explicit_replacement_and_executable(tmp_path):
    store = Store(tmp_path)
    (tmp_path / "claude.json").write_text(json.dumps({
        "executable": "/example/claude", "args": ["-p", "--model", "configured"],
    }))
    assert configuration(store, None, None, None) == (
        "/example/claude", ["-p", "--model", "configured"],
    )
    assert configuration(store, None, "custom", ["--model", "override"]) == (
        "custom", ["--model", "override"],
    )
    assert configuration(store, None, None, []) == ("/example/claude", [])


@pytest.mark.parametrize("value", [
    {"args": "--model sonnet"}, {"args": [1]}, {"args": ["bad\0argument"]},
    {"executable": ""}, {"executable": None}, {"executable": ["claude"]},
    {"arguments": []}, [],
])
def test_bad_configuration_fails_before_launch(tmp_path, value):
    (tmp_path / "claude.json").write_text(json.dumps(value))
    with pytest.raises(QuartermasterError):
        configuration(Store(tmp_path), None, None, None)


@pytest.mark.parametrize("flag", [
    "--append-system-prompt", "--append-system-prompt-file",
    "--append-system-prompt=custom", "--append-system-prompt-file=custom",
])
def test_prompt_conflicts_are_explicit(tmp_path, flag):
    with pytest.raises(QuartermasterError, match="conflicts"):
        configuration(Store(tmp_path), None, None, [flag])


def test_dry_run_packet_retains_source_context_and_legacy_gaps(tmp_path):
    state_dir = tmp_path / "state"
    store = Store(state_dir)
    document = json.loads((FIXTURES / "cswap.json").read_text())
    document["extra"] = {"forecast": [1, None, 3]}
    ingest(store, "cswap", document, "example")
    with store.locked() as state:
        state["sources"]["legacy"] = {"accounts": []}
        state["requests"]["pending"] = {"requestId": "pending", "status": "pending"}
        store.write(state)
    before = store.path.read_bytes()
    context = {"roster": [{"id": "agent-a", "mode": "human-attended"}],
               "preferences": {"reserve": 25}, "future": [None, {"v": True}]}
    path = tmp_path / "context.json"
    path.write_text(json.dumps(context))
    result = cli(state_dir, "consult", "--dry-run", "--claude", "not-installed",
                 "--context", str(path), "--question", "--not-an-option", "--", "-p")
    # argparse requires = when a value itself looks like an option.
    assert result.returncode != 0
    result = cli(state_dir, "consult", "--dry-run", "--claude", "not-installed",
                 "--context", str(path), "--question=--not-an-option", "--", "-p")
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    directory = Path(info["directory"])
    packet = json.loads((directory / "context.json").read_text())
    assert packet["evidence"]["sources"]["cswap:example"]["raw"] == document
    assert packet["consumerContext"] == context
    assert packet["sourcesWithoutRaw"] == ["legacy"]
    assert packet["evidence"]["requests"][0]["requestId"] == "pending"
    assert info["argv"][1].startswith("Quartermaster request:")
    assert store.path.read_bytes() == before
    assert not (directory / "result.json").exists()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for name in ("context.json", "instructions.txt", "invocation.json"):
        assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600


def test_empty_separator_clears_defaults_and_stays_interactive(tmp_path):
    (tmp_path / "claude.json").write_text('{"args":["-p","--model","configured"]}')
    result = cli(tmp_path, "consult", "--dry-run", "--")
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info["mode"] == "interactive"
    assert "-p" not in info["argv"]
    assert "configured" not in info["argv"]


def test_headless_native_arguments_output_and_lock_release(tmp_path, fake):
    state = tmp_path / "state"
    marker = tmp_path / "MUST_NOT_EXIST"
    forwarded = ["--print", "--model", "example model", "--tools", "",
                 "--future-option", f"$(touch {marker})", "--resume", "session-example",
                 "--output-format", "text", "--fake-lock"]
    result = cli(state, "consult", "--claude", str(fake), "--", *forwarded)
    assert result.returncode == 0, result.stderr
    assert result.stdout == b"synthetic recommendation\n\xff\n"
    assert not marker.exists()
    directory = consultation(state)
    capture = json.loads((directory / "fake-capture.json").read_text())
    assert capture["argv"][3:] == forwarded
    assert capture["tty"] == [False, False, False]
    assert capture["cwd"] == str(Path.cwd())
    assert (directory / "stdout").read_bytes() == result.stdout
    assert (directory / "stderr").read_bytes() == b"synthetic diagnostic\n"
    report = json.loads((directory / "result.json").read_text())
    assert report["status"] == "completed"
    assert report["assignmentEffect"] == "none"
    assert Store(state).read()["requests"] == {}


def test_explicit_config_and_headless_convenience(tmp_path, fake):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"executable": str(fake), "args": ["--model", "chosen"]}))
    result = cli(tmp_path / "state", "consult", "--config", str(path), "--headless")
    assert result.returncode == 0, result.stderr
    argv = json.loads((consultation(tmp_path / "state") / "fake-capture.json").read_text())["argv"]
    assert argv[3:] == ["-p", "--model", "chosen"]


def test_child_failure_keeps_output_and_status(tmp_path, fake):
    state = tmp_path / "state"
    result = cli(state, "consult", "--claude", str(fake), "--", "-p", "--fake-exit", "7")
    assert result.returncode == 7
    assert result.stdout == b"synthetic recommendation\n\xff\n"
    record = json.loads((consultation(state) / "result.json").read_text())
    assert record["exitCode"] == 7
    assert record["status"] == "failed"


def test_missing_executable_does_not_return_advice(tmp_path):
    result = cli(tmp_path, "consult", "--claude", "/not-installed/claude", "--headless")
    assert result.returncode == 1
    assert result.stdout == b""
    record = json.loads((consultation(tmp_path) / "result.json").read_text())
    assert record["status"] == "failed"
    assert record["error"]


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_invalid_timeout_does_not_start(tmp_path, timeout):
    result = cli(tmp_path, "consult", "--headless", f"--timeout={timeout}")
    assert result.returncode == 1
    assert b"finite and greater than zero" in result.stderr
    assert not (tmp_path / "consultations").exists()


def test_no_tty_requires_explicit_headless_mode(tmp_path, fake):
    result = cli(tmp_path, "consult", "--claude", str(fake))
    assert result.returncode == 1
    assert b"requires a terminal" in result.stderr
    assert not (tmp_path / "consultations").exists()


def test_headless_timeout_stops_own_group_and_retains_partial_output(tmp_path, fake):
    state = tmp_path / "state"
    result = cli(state, "consult", "--claude", str(fake), "--timeout", "0.5",
                 "--", "-p", "--fake-hang")
    assert result.returncode == 124
    assert result.stdout == b"partial output\n"
    directory = consultation(state)
    assert json.loads((directory / "result.json").read_text())["status"] == "timeout"
    capture = json.loads((directory / "fake-capture.json").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(capture["pid"], 0)
    child = int((directory / "fake-child.pid").read_text())
    # A reparented descendant can remain a zombie briefly on Linux.
    deadline = time.monotonic() + 3
    while True:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        status_path = Path(f"/proc/{child}/stat")
        try:
            if status_path.read_text().rsplit(")", 1)[1].split()[0] == "Z":
                break
        except FileNotFoundError:
            pass
        assert time.monotonic() < deadline, "consultation descendant is still running"
        time.sleep(0.02)


def test_headless_termination_cleans_up_child(tmp_path, fake):
    state = tmp_path / "state"
    process = subprocess.Popen(
        [sys.executable, "-m", "quartermaster.cli", "--state-dir", str(state),
         "consult", "--claude", str(fake), "--", "-p", "--fake-hang"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 5
        while not list(state.glob("consultations/*/fake-child.pid")):
            assert time.monotonic() < deadline
            time.sleep(0.02)
        process.send_signal(signal.SIGTERM)
        output, errors = process.communicate(timeout=5)
        assert process.returncode == 143, errors
        assert output == b"partial output\n"
        directory = consultation(state)
        assert json.loads((directory / "result.json").read_text())["status"] == "interrupted"
        capture = json.loads((directory / "fake-capture.json").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(capture["pid"], 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)


def test_interactive_exec_inherits_tty_and_does_not_hold_lock(tmp_path, fake):
    state = tmp_path / "state"
    master, slave = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "-m", "quartermaster.cli", "--state-dir", str(state),
         "consult", "--claude", str(fake), "--", "--fake-interactive", "--fake-lock"],
        stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
    )
    output = b""
    try:
        deadline = time.monotonic() + 5
        while b"FAKE READY" not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output += os.read(master, 65536)
        assert b"FAKE READY" in output, output
        directory = consultation(state)
        capture = json.loads((directory / "fake-capture.json").read_text())
        assert capture["tty"] == [True, True, True]
        assert capture["pid"] == process.pid  # exec, not another wrapper or PTY relay
        with Store(state, lock_timeout=0.1).locked() as snapshot:
            assert snapshot["requests"] == {}
        document = json.loads((FIXTURES / "cswap.json").read_text())
        ingest(Store(state, lock_timeout=0.1), "cswap", document, "new-observation")
        assert Store(state).read()["sources"]["cswap:new-observation"]["raw"] == document
        packet = json.loads((directory / "context.json").read_text())
        assert packet["evidence"]["sources"] == {}  # the original snapshot does not change
        os.write(master, b"follow-up question\n")
        process.wait(timeout=5)
        assert process.returncode == 0
        while select.select([master], [], [], 0.1)[0]:
            output += os.read(master, 65536)
        assert b"FAKE INPUT: follow-up question" in output
        assert not (directory / "result.json").exists()  # native Claude owns its history
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def test_forwarding_is_not_silently_accepted_by_other_commands(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["--state-dir", str(tmp_path), "status", "--", "--model", "anything"])
    assert error.value.code == 2


def test_existing_end_of_options_syntax_remains_supported(tmp_path):
    result = cli(tmp_path, "view", "--", "auto")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mode"] == "auto"


def test_consult_requires_separator_before_forwarded_arguments(tmp_path):
    result = cli(tmp_path, "consult", "a stray positional prompt")
    assert result.returncode == 2
    assert b"use -- before Claude arguments" in result.stderr
