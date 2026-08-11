from types import SimpleNamespace

from app.tasking.celery_app import _worker_hostname


def test_worker_hostname_supports_worker_and_heartbeat_signal_senders() -> None:
    worker_sender = SimpleNamespace(controller=SimpleNamespace(hostname="worker@test"))
    heartbeat_sender = SimpleNamespace(eventer=SimpleNamespace(hostname="data@test"))

    assert _worker_hostname(worker_sender) == "worker@test"
    assert _worker_hostname(heartbeat_sender) == "data@test"
    assert _worker_hostname(None) == "unknown-worker"
