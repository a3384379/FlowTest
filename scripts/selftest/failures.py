"""Safe failure receipts, including SDK task-group failures without payload disclosure."""

from __future__ import annotations

import re

from scripts.selftest.io import HarnessError


def failure_codes(error: BaseException) -> tuple[str, ...]:
    if isinstance(error, BaseExceptionGroup):
        codes = [code for child in error.exceptions for code in failure_codes(child)]
        return tuple(dict.fromkeys(codes))[:20]
    if isinstance(error, HarnessError):
        match = re.match(r"(SELFTEST_[A-Z0-9_]+)(?::([A-Z][A-Z0-9_]{0,99}))?", str(error))
        if match is None:
            return ("SELFTEST_HARNESS_ERROR",)
        return ("_".join(value for value in match.groups() if value is not None),)
    return ("SELFTEST_" + type(error).__name__.upper(),)
