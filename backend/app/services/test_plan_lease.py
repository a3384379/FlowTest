"""Renew only an unexpired owned claim; losing ownership stops the local worker."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.tasking import TaskingRepository


async def maintain_worker_lease(
    session_maker: async_sessionmaker[AsyncSession],
    run_id: UUID,
    owner: str,
    seconds: int,
    parent: asyncio.Task[None],
    completing: asyncio.Event,
) -> None:
    try:
        while True:
            await asyncio.sleep(seconds / 3)
            now = datetime.now(UTC)
            async with session_maker() as session:
                renewed = await TaskingRepository(session).renew_worker_lease(
                    run_id, owner, now, now + timedelta(seconds=seconds)
                )
                await session.commit()
                run = await TaskingRepository(session).get_run(run_id) if not renewed else None
            if not renewed:
                if (
                    completing.is_set()
                    and run is not None
                    and run.status in {"passed", "failed", "cancelled"}
                ):
                    return
                parent.cancel()
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        parent.cancel()
        raise
