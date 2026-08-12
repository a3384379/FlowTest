#!/usr/bin/env python3
"""Verify the stable FlowTest Kafka client against Apache Kafka in CI."""

from __future__ import annotations

import asyncio
import json
import os
import secrets

from app.domain.event_protocols import KafkaOffset
from app.services.event_runtime import ConfluentKafkaGateway


async def verify() -> None:
    bootstrap = os.getenv("FLOWTEST_KAFKA_COMPAT_BOOTSTRAP", "localhost:29092")
    topic = os.getenv("FLOWTEST_KAFKA_COMPAT_TOPIC", "flowtest.compat")
    correlation_id = f"compat-{secrets.token_hex(8)}".encode()
    gateway = ConfluentKafkaGateway()
    produced = await gateway.produce(
        bootstrap_servers=(bootstrap,),
        topic=topic,
        key=None,
        value=json.dumps({"id": correlation_id.decode()}).encode(),
        headers=(("flowtest-correlation-id", correlation_id),),
        timeout_seconds=30,
    )
    consumed = await gateway.consume(
        bootstrap_servers=(bootstrap,),
        topic=topic,
        offset=KafkaOffset.EARLIEST,
        maximum_messages=1000,
        correlation_header="flowtest-correlation-id",
        correlation_id=correlation_id,
        timeout_seconds=30,
    )
    if produced.topic != topic or len(consumed) != 1 or consumed[0].value != produced.value:
        raise RuntimeError("Apache Kafka compatibility verification failed")
    print(
        json.dumps(
            {
                "status": "passed",
                "broker": "Apache Kafka 4.3.1",
                "topic": topic,
                "auto_commit": False,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(verify())
