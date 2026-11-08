"""Owned target expiry is explicit and cannot silently drift or affect runner auth."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from scripts.selftest import local_stack
from scripts.selftest.io import HarnessError, read_json
from scripts.selftest.target_auth_policy import (
    freeze_target_auth_policy,
    token_minutes,
    validate_target_auth_policy,
    verify_target_token_environment,
)

PROJECT = "flowtest-selftest-" + "a" * 12
NONCE = "b" * 32


@pytest.mark.parametrize("value", ["0", "61", "true", "01", "1.0", " 1", chr(0x661), ""])
def test_target_auth_policy_rejects_invalid_or_coerced_lifetime(value: str) -> None:
    with pytest.raises(HarnessError, match="TARGET_AUTH_POLICY_INVALID"):
        token_minutes({"FLOWTEST_SELFTEST_TARGET_ACCESS_TOKEN_MINUTES": value})


@pytest.mark.parametrize("value", [0, 61, True, "1"])
def test_owned_stack_rejects_invalid_lifetime_before_docker(value) -> None:
    with pytest.raises(HarnessError, match="TARGET_AUTH_POLICY_INVALID"):
        local_stack._new_environment("unused", PROJECT, NONCE, target_access_token_minutes=value)


def test_legacy_default_stack_and_runner_auth_remain_compatible(tmp_path: Path) -> None:
    assert token_minutes({}) == "15"
    validate_target_auth_policy(tmp_path, PROJECT, NONCE, {})
    verify_target_token_environment({}, {})
    local_stack._verify_private_configuration(
        "runner",
        {
            "Config": {
                "Env": [
                    "FLOWTEST_SECRET_KEY=runner",
                    "FLOWTEST_DATA_ENCRYPTION_KEY=runner-encryption",
                    "FLOWTEST_SELFTEST_FIXTURE_RUN_DEPTH=0",
                    "FLOWTEST_ACCESS_TOKEN_MINUTES=15",
                ]
            }
        },
        {
            "FLOWTEST_SELFTEST_RUNNER_KEY": "runner",
            "FLOWTEST_SELFTEST_RUNNER_ENCRYPTION_KEY": "runner-encryption",
            "FLOWTEST_SELFTEST_TARGET_ACCESS_TOKEN_MINUTES": "1",
        },
    )


def test_nondefault_policy_requires_exact_nonce_receipt_and_container_value(tmp_path: Path) -> None:
    private = {"FLOWTEST_SELFTEST_TARGET_ACCESS_TOKEN_MINUTES": "1"}
    with pytest.raises(HarnessError, match="POLICY_BINDING_MISMATCH"):
        validate_target_auth_policy(tmp_path, PROJECT, NONCE, private)
    freeze_target_auth_policy(tmp_path, PROJECT, NONCE, private)
    validate_target_auth_policy(tmp_path, PROJECT, NONCE, private)
    receipt = read_json(tmp_path / "target-auth-policy.json")
    assert receipt["target_access_token_minutes"] == 1
    verify_target_token_environment({"FLOWTEST_ACCESS_TOKEN_MINUTES": "1"}, private)
    with pytest.raises(HarnessError, match="CONTAINER_POLICY_MISMATCH"):
        verify_target_token_environment({}, private)
    with pytest.raises(HarnessError, match="POLICY_BINDING_MISMATCH"):
        validate_target_auth_policy(tmp_path, PROJECT, "c" * 32, private)
    with pytest.raises(HarnessError, match="POLICY_CHANGED"):
        freeze_target_auth_policy(
            tmp_path, PROJECT, NONCE, {"FLOWTEST_SELFTEST_TARGET_ACCESS_TOKEN_MINUTES": "15"}
        )
