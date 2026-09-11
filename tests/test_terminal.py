"""Exercise the actual curses process through a PTY and a terminal emulator."""

import codecs
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from contextlib import contextmanager

import pyte

from quartermaster.core import Store


@contextmanager
def terminal(directory, rotate="0.2"):
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 9, 44, 0, 0))
    base = [sys.executable, "-m", "quartermaster.cli", "--state-dir", str(directory)]
    process = subprocess.Popen(
        base + ["tui", "--refresh", "0.05", "--rotate", rotate],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        env={**os.environ, "TERM": "xterm-256color"},
    )
    screen = pyte.Screen(44, 9)
    stream = pyte.Stream(screen)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def wait(predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.05)
            if ready:
                stream.feed(decoder.decode(os.read(master, 65536)))
            if predicate(screen):
                return
        raise AssertionError("\n".join(screen.display))

    try:
        yield base, master, slave, process, screen, wait
        os.write(master, b"q")
        wait(lambda _: process.poll() is not None)
        assert process.returncode == 0
        restored = termios.tcgetattr(slave)
        for attributes in (original, restored):
            attributes[3] &= ~getattr(termios, "PENDIN", 0)
        assert restored == original
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        os.close(master)
        os.close(slave)


def populate(directory):
    # Only synthetic normalized evidence is needed to test the live display boundary.
    accounts = [
        {
            "identity": f"id-{i}",
            "label": f"account-{i}",
            "provider": "example",
            "source": "fixture",
            "host": "fixture",
            "usageStatus": "ok",
            "measurementAt": "2099-01-01T00:00:00Z",
            "windows": [
                {"scope": "weekly", "percentRemaining": 25, "resetsAt": "2099-01-07T00:00:00Z"}
            ],
        }
        for i in range(1, 12)
    ]
    store = Store(directory)
    with store.locked() as state:
        state["sources"] = {"fixture": {"accounts": accounts}}
        store.write(state)


def test_live_keyboard_agent_selection_background_resize_and_restart(tmp_path):
    populate(tmp_path)
    with terminal(tmp_path, "0.3") as (base, master, slave, process, screen, wait):
        wait(lambda s: "account 1 of 11" in s.display[-1])
        assert screen.buffer[0][0].bg == "black"
        assert screen.display[1] == "█" * 11 + "░" * 33, screen.display
        os.write(master, b"3")
        wait(lambda s: "account 3 of 11 HOLD" in s.display[-1])
        held_until = time.monotonic() + 0.5
        wait(lambda s: time.monotonic() >= held_until)
        assert "account 3 of 11 HOLD" in screen.display[-1]
        os.write(master, b" ")
        wait(lambda s: "account 4 of 11 HOLD" in s.display[-1])
        os.write(master, b"\x1bOD")
        wait(lambda s: "account 3 of 11 HOLD" in s.display[-1])
        subprocess.run(base + ["view", "11"], check=True, capture_output=True)
        wait(lambda s: "account 11 of 11 HOLD" in s.display[-1])
        os.write(master, b"r")
        wait(lambda s: "account 1 of 11 AUTO" in s.display[-1])
        subprocess.run(base + ["view", "11"], check=True, capture_output=True)
        wait(lambda s: "account 11 of 11 HOLD" in s.display[-1])
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 6, 32, 0, 0))
        screen.resize(lines=6, columns=32)
        process.send_signal(signal.SIGWINCH)
        wait(lambda s: any("account 11 of 11 HOLD" in line for line in s.display))
    with terminal(tmp_path, "0") as (_, _, _, _, _, wait):
        wait(lambda s: "account 11 of 11 HOLD" in s.display[-1])


def test_live_rotation_visits_every_account(tmp_path):
    populate(tmp_path)
    seen = set()
    with terminal(tmp_path) as (_, _, _, _, _, wait):

        def complete(screen):
            footer = screen.display[-1].split()
            if len(footer) >= 5 and footer[0] == "account" and footer[2] == "of":
                seen.add(int(footer[1]))
            return len(seen) == 11

        wait(complete)
    assert seen == set(range(1, 12))


def test_no_color_terminal_fails_and_restores_state(tmp_path):
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "quartermaster.cli",
            "--state-dir",
            str(tmp_path),
            "tui",
        ],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        env={**os.environ, "TERM": "dumb"},
    )
    output = bytearray()
    deadline = time.monotonic() + 5
    try:
        while process.poll() is None and time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.05)
            if ready:
                output.extend(os.read(master, 65536))
        process.wait(timeout=1)
        while True:
            ready, _, _ = select.select([master], [], [], 0)
            if not ready:
                break
            output.extend(os.read(master, 65536))
        assert process.returncode == 1
        assert b"Terminal color support is required" in output
        restored = termios.tcgetattr(slave)
        for attributes in (original, restored):
            attributes[3] &= ~getattr(termios, "PENDIN", 0)
        assert restored == original
        once = subprocess.run(
            [
                sys.executable,
                "-m",
                "quartermaster.cli",
                "--state-dir",
                str(tmp_path),
                "tui",
                "--once",
            ],
            env={**os.environ, "TERM": "dumb"},
            capture_output=True,
            check=False,
        )
        assert once.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        os.close(master)
        os.close(slave)
