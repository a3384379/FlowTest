"""Independent O-signed all-attempt history resists reset, rewriting and tail replay."""

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.selftest.contracts import canonical_digest  # noqa: E402
from scripts.selftest.host_launch import VerifiedGrant  # noqa: E402
from scripts.selftest.host_quality import QualityAttempt, QualityTask, QualityTaskSet  # noqa: E402
from scripts.selftest.host_quality_history import QualityHistory, QualitySeries  # noqa: E402
from scripts.selftest.io import HarnessError, read_json, write_json  # noqa: E402
from scripts.selftest.product_agent_client import AgentIdentity  # noqa: E402
from test_selftest_host_adapter import authorization  # noqa: E402

from app.core.self_tests import SelfTestPrincipal  # noqa: E402


def context(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    directory = tmp_path / "observer"
    directory.mkdir(mode=0o700)
    path = directory / "o.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    auth = authorization()
    principal = SelfTestPrincipal(
        id="independent-o",
        issuer="selftest-o",
        subject="observer",
        audience="selftest",
        public_key=key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
        allowed_project_ids=(auth.project_id,),
        allowed_binding_ids=(uuid4(),),
        capabilities=("verify",),
        trusted_verifier=True,
    )
    signer = AgentIdentity(principal=principal, private_key_file=path)
    grant = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    taskset = QualityTaskSet(version="fixed-benchmark-v1", tasks=(QualityTask(task_id="one"),))
    history = QualityHistory.for_task(tmp_path / "harness", grant, taskset, principal)
    return history, grant, signer, taskset


def measured(attempt, *, matched):
    return (
        QualityAttempt(
            task_id="one",
            attempt_id=attempt,
            ordinal=1,
            evidence_digest="a" * 64,
            review_mode="ci_fixture",
            protocol_available=True,
            design_valid=True,
            executable_asset_generated=True,
            independent_execution_match=matched,
            source_complete=True,
        ),
    )


def test_new_signed_grants_get_continuous_ordinals_and_first_failure_never_disappears(tmp_path):
    history, grant, signer, _ = context(tmp_path)
    first = uuid4()
    assert history.reserve(grant, first) == 1
    history.finish(grant, first, measured(first, matched=False), signer=signer)
    auth = grant.authorization.model_copy(
        update={"authorization_id": uuid4(), "batch_key": "new-authorized-batch"}
    )
    later = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    second = uuid4()
    assert history.reserve(later, second) == 2
    report = history.finish(later, second, measured(second, matched=True), signer=signer)
    assert [item.ordinal for item in report.attempts] == [1, 2]
    first_metric = next(
        item for item in report.metrics if item.name == "first_generation_execution_match"
    )
    assert (first_metric.numerator, first_metric.denominator) == (0, 1)
    assert history.report(signer=signer) == report


def test_unsigned_measurement_or_terminal_rewrite_is_rejected(tmp_path):
    history, grant, signer, _ = context(tmp_path)
    attempt = uuid4()
    history.reserve(grant, attempt)
    with pytest.raises(HarnessError, match="SIGNATURE_REQUIRED"):
        history.finish(grant, attempt, measured(attempt, matched=True))
    history.finish(grant, attempt, measured(attempt, matched=False), signer=signer)
    with pytest.raises(HarnessError, match="TERMINAL_REWRITE"):
        history.finish(grant, attempt, measured(attempt, matched=True), signer=signer)


@pytest.mark.parametrize("change", ["signed_tail", "old_prefix", "new_harness_directory"])
def test_private_observer_checkpoint_rejects_tail_truncation_and_prefix_replay(change, tmp_path):
    history, grant, signer, taskset = context(tmp_path)
    attempt = uuid4()
    history.reserve(grant, attempt)
    old_head = read_json(history.head)
    history.finish(grant, attempt, measured(attempt, matched=False), signer=signer)
    if change == "signed_tail":
        (history.directory / "event-002.json").unlink()
    elif change == "old_prefix":
        (history.directory / "event-002.json").unlink()
        write_json(history.head, old_head)
    else:
        history = QualityHistory.for_task(
            tmp_path / "new-harness", grant, taskset, signer.principal
        )
        history.reserve(grant, attempt)
    with pytest.raises(
        HarnessError, match=r"HISTORY_INCOMPLETE|CHECKPOINT_ROLLBACK|CHECKPOINT_FORK"
    ):
        history.report(signer=signer)


def test_same_taskset_cannot_silently_change_model_or_skill_or_reset_grant(tmp_path):
    history, grant, signer, taskset = context(tmp_path)
    attempt = uuid4()
    history.reserve(grant, attempt)
    with pytest.raises(HarnessError, match="GRANT_REUSED"):
        history.reserve(grant, uuid4())
    changed = QualityHistory(
        history.directory,
        QualitySeries.frozen(
            VerifiedGrant(grant.authorization.model_copy(update={"model": "other"}), grant.digest),
            taskset,
            signer.principal,
        ),
    )
    with pytest.raises(HarnessError, match="SCOPE_CHANGED"):
        changed.report()


@pytest.mark.parametrize("empty", [True, False])
def test_zero_sequence_observer_checkpoint_is_explicitly_rejected(tmp_path, empty):
    history, grant, signer, _ = context(tmp_path)
    if not empty:
        history.reserve(grant, uuid4())
    write_json(
        history._checkpoint_path(signer),
        {
            "series": history.series.model_dump(mode="json"),
            "sequence": 0,
            "digest": canonical_digest(history.series.model_dump(mode="json")),
        },
    )
    with pytest.raises(HarnessError, match="HOST_QUALITY_CHECKPOINT_CORRUPT"):
        history.report(signer=signer)


def test_assisted_reservation_does_not_enter_model_first_generation_denominator(tmp_path):
    history, grant, _, _ = context(tmp_path)
    history.reserve(grant, uuid4(), assisted=True)
    report = history.report()
    for name in ("protocol_availability", "first_generation_execution_match"):
        metric = next(item for item in report.metrics if item.name == name)
        assert metric.denominator == 0 and metric.status == "NOT_EVALUATED"


def test_observer_signature_binds_measurements_even_when_harness_rehashes_chain(tmp_path):
    history, grant, signer, _ = context(tmp_path)
    attempt = uuid4()
    history.reserve(grant, attempt)
    history.finish(grant, attempt, measured(attempt, matched=False), signer=signer)
    path = history.directory / "event-002.json"
    event = read_json(path)
    event["attempts"][0]["independent_execution_match"] = True
    write_json(path, event)
    head = read_json(history.head)
    head["digest"] = canonical_digest(event)
    write_json(history.head, head)
    with pytest.raises(HarnessError, match="HOST_QUALITY_OBSERVER_SIGNATURE_CHANGED"):
        history.report(signer=signer)


def test_unsigned_unknown_first_attempt_stays_incomplete_after_later_observed_success(tmp_path):
    history, grant, signer, _ = context(tmp_path)
    first = uuid4()
    history.reserve(grant, first)
    with pytest.raises(HarnessError, match="UNSIGNED_MEASUREMENT_FORBIDDEN"):
        history.finish(grant, first, measured(first, matched=True), failed=True)
    unknown = measured(first, matched=False)[0].model_copy(
        update={
            "protocol_available": None,
            "design_valid": None,
            "executable_asset_generated": None,
            "independent_execution_match": None,
            "source_complete": False,
        }
    )
    history.finish(grant, first, (unknown,), failed=True)
    auth = grant.authorization.model_copy(
        update={"authorization_id": uuid4(), "batch_key": "explicitly-new-grant"}
    )
    later = VerifiedGrant(auth, canonical_digest(auth.model_dump(mode="json")))
    second = uuid4()
    assert history.reserve(later, second) == 2
    report = history.finish(later, second, measured(second, matched=True), signer=signer)
    first_metric = next(
        item for item in report.metrics if item.name == "first_generation_execution_match"
    )
    assert (first_metric.numerator, first_metric.denominator, first_metric.status) == (
        0,
        1,
        "INCOMPLETE",
    )
    assert report.evaluation_status == "INCOMPLETE" and len(report.attempts) == 2
