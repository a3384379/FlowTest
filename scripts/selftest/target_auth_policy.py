"""Explicit target-only JWT lifetime for owned expiry fixtures, without app defaults."""

from pathlib import Path
from typing import Literal

from pydantic import Field, StrictInt
from scripts.selftest.contracts import Contract
from scripts.selftest.io import HarnessError, read_json, write_json


class TargetAuthPolicy(Contract):
    schema_version: Literal["flowtest-owned-target-auth-v1"] = "flowtest-owned-target-auth-v1"
    project_name: str = Field(pattern=r"^flowtest-selftest-[0-9a-f]{12}$")
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    target_access_token_minutes: StrictInt = Field(ge=1, le=60)
    purpose: Literal["owned_target_authentication_fixture"] = "owned_target_authentication_fixture"


def token_minutes(private: dict[str, str]) -> str:
    value = private.get("FLOWTEST_SELFTEST_TARGET_ACCESS_TOKEN_MINUTES", "15")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 60:
        raise HarnessError("SELFTEST_TARGET_AUTH_POLICY_INVALID")
    if str(int(value)) != value:
        raise HarnessError("SELFTEST_TARGET_AUTH_POLICY_INVALID")
    return value


def freeze_target_auth_policy(
    directory: Path, project: str, nonce: str, private: dict[str, str]
) -> None:
    policy = TargetAuthPolicy(
        project_name=project, nonce=nonce, target_access_token_minutes=int(token_minutes(private))
    )
    path = directory / "target-auth-policy.json"
    if path.exists() and read_json(path) != policy.model_dump(mode="json"):
        raise HarnessError("SELFTEST_TARGET_AUTH_POLICY_CHANGED")
    if not path.exists():
        write_json(path, policy)


def validate_target_auth_policy(
    directory: Path, project: str, nonce: str, private: dict[str, str]
) -> None:
    path = directory / "target-auth-policy.json"
    minutes = token_minutes(private)
    if not path.exists() and "FLOWTEST_SELFTEST_TARGET_ACCESS_TOKEN_MINUTES" not in private:
        return  # Previously frozen stacks use the unchanged application default of 15.
    expected = TargetAuthPolicy(
        project_name=project, nonce=nonce, target_access_token_minutes=int(minutes)
    )
    if not path.exists() or read_json(path) != expected.model_dump(mode="json"):
        raise HarnessError("SELFTEST_TARGET_AUTH_POLICY_BINDING_MISMATCH")


def verify_target_token_environment(environment: dict[str, str], private: dict[str, str]) -> None:
    # Legacy default stacks do not set this optional environment variable.
    if environment.get("FLOWTEST_ACCESS_TOKEN_MINUTES", "15") != token_minutes(private):
        raise HarnessError("SELFTEST_TARGET_AUTH_CONTAINER_POLICY_MISMATCH")
