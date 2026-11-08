"""Real OS-pipe test relay; fixture PID handle, not deployed Linux identity proof."""

import os
import subprocess
import sys
from pathlib import Path

from scripts.selftest.mcp_fault_contracts import ProcessIdentity
from scripts.selftest.mcp_fault_stdio import PipeRelay


def main() -> None:
    fault, nonce, output = sys.argv[1:]
    server = Path(__file__).with_name("mcp_fault_server.py")
    child = subprocess.Popen(
        [sys.executable, str(server)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "FLOWTEST_FAULT_FIXTURE_TRANSPORT": "stdio"},
    )

    def identity() -> ProcessIdentity:
        # Only the deployed control path reads Linux /proc start_ticks. This
        # macOS mechanical fixture owns the exact Popen handle instead.
        assert child.poll() is None
        return ProcessIdentity(nonce=nonce, pid=child.pid, start_ticks="1")

    def crash(selected: ProcessIdentity) -> None:
        assert selected.pid == child.pid and child.poll() is None
        child.kill()
        assert child.wait(timeout=5) != 0

    try:
        PipeRelay(nonce, fault, Path(output), child, identity, crash).run()
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


if __name__ == "__main__":
    main()
