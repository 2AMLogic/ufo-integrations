"""A store and a tool context for pulse's own tests, built without touching the matrix extension.

The two extensions pin and activate independently (`extensions/test_distribution_pins.py`), and a
pulse test importing matrix's fakes would make that independence true of the distribution and false
of the suite. So this is pulse's own: the two tables over an in-memory database, a context that
reaches them, and a carrier that can be present, absent, or broken — the three states the projection
has to tell apart.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ufo_ext_pulse.record import COVERED_TABLE, SIGHTING_TABLE


async def store_engine() -> AsyncEngine:
    """The extension's tables over a fresh in-memory database, beside the one core column they
    reference. Built from the same `sa.Table` objects the handlers query, so a column this suite
    exercises is a column the handlers see; that the *migration* creates these same tables is
    asserted against the real DDL in `test_registry.py`, which is the half this cannot check."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("workspace", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    for table in (SIGHTING_TABLE, COVERED_TABLE):
        table.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    return engine


@dataclass
class Files:
    """A carrier that takes workspace files. `written` is what landed, last write per path."""

    written: dict[str, bytes] = field(default_factory=dict)
    breaks: bool = False

    async def write(self, conversation_id: UUID, rel: str, content: bytes) -> str:
        if self.breaks:
            raise RuntimeError("the conversation has no live sandbox")
        self.written[rel] = content
        return f"/workspace/{rel}"

    def text(self, rel: str) -> str:
        return self.written[rel].decode()


@dataclass
class Store:
    """An `ExtensionContext` as the record module and the handlers use one: a workspace id, a
    transaction, and a carrier that may or may not be able to take a file."""

    engine: AsyncEngine
    workspace_id: UUID = field(default_factory=uuid4)
    files: Files | None = field(default_factory=Files)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self.engine.begin() as connection:
            yield connection


def tool_context(store: Store, conversation_id: UUID | None = None) -> SimpleNamespace:
    """What a handler reads off its `ToolContext`: the extension context and the conversation the
    projection lands in. Nothing else on a real one is touched, and a stand-in that grew a field a
    handler does not read would be a claim about core rather than about pulse."""
    return SimpleNamespace(ext=store, turn=SimpleNamespace(conversation_id=conversation_id or uuid4()))


def on_store(test: Callable[..., Awaitable[None]]) -> Callable[..., None]:
    """Run an async test on its own loop with a fresh `Store`, so the suite needs no async pytest
    plugin and every engine lives and dies on the loop that made it."""
    params = [p for p in inspect.signature(test).parameters.values() if p.name != "store"]

    @functools.wraps(test)
    def run(*args: object, **kwargs: object) -> None:
        async def scenario() -> None:
            engine = await store_engine()
            try:
                await test(*args, store=Store(engine=engine), **kwargs)
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    run.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    return run
