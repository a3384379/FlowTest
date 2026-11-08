"""Read-only owned PostgreSQL regression, distinct from public O acceptance."""

import os
import unittest
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services.self_test_probe_rows import probe_rows


@unittest.skipUnless(
    os.getenv("FLOWTEST_TEST_PROBE_POSTGRES_OWNED") == "1",
    "需要显式指定已拥有的 PostgreSQL; 普通 SQLite 测试不替代此行为",
)
class ProbePostgreSQLRegression(unittest.IsolatedAsyncioTestCase):
    async def test_empty_scoped_inventory_executes_all_ten_union_branches_on_postgresql(
        self,
    ) -> None:
        self.assertTrue(settings.database_url.startswith("postgresql+asyncpg://"))
        engine = create_async_engine(settings.database_url)
        sessions = async_sessionmaker(engine, class_=AsyncSession)
        try:
            async with sessions() as session:
                # Random nonexistent IDs exercise SQL type resolution without writes
                # or using business-table counts as expected verification evidence.
                count, rows = await probe_rows(session, (uuid4(), uuid4()))
                self.assertEqual((count, rows), (0, ()))
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
