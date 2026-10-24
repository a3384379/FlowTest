"""Run the mock app's isolated tests without importing it as the backend app package."""

import subprocess
import sys
from pathlib import Path


def test_mock_fixture_business_and_observer_contracts() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--no-cov",
            "-q",
            "tests/test_selftest.py",
            "tests/test_selftest_budget.py",
        ],
        cwd=root / "mock-target",
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
