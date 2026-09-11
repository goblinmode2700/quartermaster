#!/usr/bin/env python3
"""A synthetic CLI peer. Never contacts Claude or a provider."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

arguments = sys.argv[1:]
instructions = Path(arguments[arguments.index("--append-system-prompt-file") + 1])
directory = instructions.parent
packet = json.loads((directory / "context.json").read_text())
instruction_text = instructions.read_text()
assert json.dumps(packet, indent=2) in instruction_text

capture = {
    "argv": arguments,
    "cwd": str(Path.cwd()),
    "tty": [os.isatty(fd) for fd in range(3)],
    "pid": os.getpid(),
    "prompt": instruction_text,
}
(directory / "fake-capture.json").write_text(json.dumps(capture))

if "--fake-lock" in arguments:
    import fcntl

    with (directory.parent.parent / "state.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock, fcntl.LOCK_UN)

if "--fake-hang" in arguments:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (directory / "fake-child.pid").write_text(str(child.pid))
    os.write(1, b"partial output\n")
    time.sleep(60)

if "--fake-interactive" in arguments:
    print("FAKE READY", flush=True)
    print("FAKE INPUT: " + input(), flush=True)
else:
    os.write(1, b"synthetic recommendation\n\xff\n")
    os.write(2, b"synthetic diagnostic\n")

if "--fake-exit" in arguments:
    raise SystemExit(int(arguments[arguments.index("--fake-exit") + 1]))
