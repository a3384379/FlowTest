import os

import pytest

from app.core.database import check_database
from app.core.redis import check_redis
from app.core.storage import check_storage, ensure_storage_bucket

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FLOWTEST_RUN_INTEGRATION") != "1",
        reason="Set FLOWTEST_RUN_INTEGRATION=1 to run infrastructure tests",
    ),
]


async def test_postgres_redis_and_storage_are_available() -> None:
    await check_database()
    await check_redis()
    await ensure_storage_bucket()
    await check_storage()
