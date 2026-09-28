"""The historical record a brief series builds: the sightings pool and the covered ledger, in tables
this extension's own migration owns.

**Why a table and not the workspace file alone.** The file is written by running `seen.py` or
`covered.py` as a command, and a command tool belongs to the terminal client rather than to any
extension. A scheduled fire has no client, so it gathered, ranked, replied — and recorded nothing.
A record that accumulates only while someone is watching is not a historical record. The write that
matters therefore goes to the deploy's database, which is reachable on every fire (#120).

**Why the file survives anyway.** It is the half a member can open. So it stays, as a *projection*:
rendered whole from the table after each write, landed in the conversation workspace when a carrier
can take it, and authoritative never. Rendering the whole file rather than appending to it is what
keeps the two from drifting — there is no state in the file that the table does not hold, so a
projection written after a gap simply catches up.

**The row shapes are the file's, unchanged.** A projected line is byte-identical to the line the
scripts used to append, because the scripts are still the reader a member and a sandbox command use.
`tests/test_record_store.py` pins that equality against the skill's own source rather than trusting
this sentence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

# These three shapes are the skills' own, restated here because a skill script is materialised
# standalone in a sandbox and cannot import this package. `test_record_store.py` reads the pattern
# out of `_jsonl_pool.py` and the two date patterns out of their scripts and asserts they match, so
# the duplication is checked rather than trusted.
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

POOL_DIR = "pulse"
DEFAULT_WITHIN_DAYS = 14
DEFAULT_EDITIONS = 5

_metadata = sa.MetaData()


def _workspace() -> sa.ForeignKey:
    return sa.ForeignKey("workspace.id", ondelete="CASCADE")


SIGHTING_TABLE = sa.Table(
    "pulse_ext_sighting",
    _metadata,
    sa.Column("workspace_id", sa.Uuid(), _workspace(), primary_key=True),
    sa.Column("series", sa.Text(), primary_key=True),
    sa.Column("seen", sa.Text(), primary_key=True),
    sa.Column("slug", sa.Text(), primary_key=True),
    sa.Column("url", sa.Text(), primary_key=True),
    sa.Column("title", sa.Text(), nullable=False),
    sa.Column("source", sa.Text(), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
)

COVERED_TABLE = sa.Table(
    "pulse_ext_covered",
    _metadata,
    sa.Column("workspace_id", sa.Uuid(), _workspace(), primary_key=True),
    sa.Column("series", sa.Text(), primary_key=True),
    sa.Column("edition", sa.Text(), primary_key=True),
    sa.Column("slug", sa.Text(), primary_key=True),
    sa.Column("title", sa.Text(), nullable=False),
    sa.Column("url", sa.Text(), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
)


class Transactional(Protocol):
    """What a store call needs of its `ExtensionContext`, and nothing more."""

    workspace_id: UUID

    def transaction(self) -> AbstractAsyncContextManager[AsyncConnection]: ...


@dataclass(frozen=True)
class Sighting:
    seen: str
    slug: str
    title: str
    url: str
    source: str = ""


@dataclass(frozen=True)
class Story:
    slug: str
    title: str
    url: str = ""


def check_series(series: str) -> str:
    if not SLUG.match(series):
        raise ValueError(f"series must be a lowercase hyphenated slug, got {series!r}")
    return series


def check_sighting(row: Sighting) -> Sighting:
    if not DATE.match(row.seen):
        raise ValueError(f"seen must be YYYY-MM-DD, got {row.seen!r}")
    if not SLUG.match(row.slug):
        raise ValueError(f"slug must be a lowercase hyphenated slug, got {row.slug!r}")
    # The url is the one key a reconciler can work from later: title drifts legitimately between
    # sightings and source cannot tell two stories from one publisher apart. A blank url is as
    # unreconcilable as a missing one, and it is also part of this row's primary key, so a
    # whitespace-only url would silently collapse every such sighting of a lead into one row.
    url = row.url.strip()
    if not url:
        raise ValueError("url is required: a sighting with no url cannot be reconciled later")
    return Sighting(seen=row.seen, slug=row.slug, title=row.title, url=url, source=row.source)


def check_story(edition: str, row: Story) -> Story:
    if not DATE.match(edition):
        raise ValueError(f"edition must be YYYY-MM-DD, got {edition!r}")
    if not SLUG.match(row.slug):
        raise ValueError(f"slug must be a lowercase hyphenated slug, got {row.slug!r}")
    return row


async def _upsert(
    connection: AsyncConnection,
    table: sa.Table,
    key: Mapping[str, Any],
    values: Mapping[str, Any],
) -> None:
    """Write the row whether or not it is already there, without a dialect-specific insert.

    An update that matches nothing is followed by an insert. Two fires racing on one key is not a
    case this needs to win: both carry the same facts by construction — the key is every field that
    distinguishes one sighting from another — so whichever lands second writes what the first did.
    """
    where = sa.and_(*(table.c[name] == value for name, value in key.items()))
    updated = await connection.execute(sa.update(table).where(where).values(**values))
    if updated.rowcount == 0:
        await connection.execute(sa.insert(table).values(**key, **values))


async def record_sightings(
    ctx: Transactional, series: str, rows: Sequence[Sighting], now: datetime
) -> int:
    """Record what a gather saw. Returns the number of rows written, duplicates included."""
    check_series(series)
    checked = [check_sighting(row) for row in rows]
    async with ctx.transaction() as connection:
        for row in checked:
            await _upsert(
                connection,
                SIGHTING_TABLE,
                {
                    "workspace_id": ctx.workspace_id,
                    "series": series,
                    "seen": row.seen,
                    "slug": row.slug,
                    "url": row.url,
                },
                {"title": row.title, "source": row.source, "recorded_at": now},
            )
    return len(checked)


async def record_covered(
    ctx: Transactional, series: str, edition: str, rows: Sequence[Story], now: datetime
) -> int:
    """Record what an edition published. Returns the number of rows written."""
    check_series(series)
    checked = [check_story(edition, row) for row in rows]
    async with ctx.transaction() as connection:
        for row in checked:
            await _upsert(
                connection,
                COVERED_TABLE,
                {
                    "workspace_id": ctx.workspace_id,
                    "series": series,
                    "edition": edition,
                    "slug": row.slug,
                },
                {"title": row.title, "url": row.url, "recorded_at": now},
            )
    return len(checked)


async def read_sightings(ctx: Transactional, series: str) -> list[dict]:
    """Every sighting of one series, oldest first — the pool, in the shape the file holds it."""
    check_series(series)
    async with ctx.transaction() as connection:
        rows = (
            await connection.execute(
                sa.select(
                    SIGHTING_TABLE.c.seen,
                    SIGHTING_TABLE.c.slug,
                    SIGHTING_TABLE.c.title,
                    SIGHTING_TABLE.c.url,
                    SIGHTING_TABLE.c.source,
                )
                .where(
                    SIGHTING_TABLE.c.workspace_id == ctx.workspace_id,
                    SIGHTING_TABLE.c.series == series,
                )
                # By the sighting's own date rather than the row's write time: a pool caught up
                # after a gap would otherwise read in the order it was repaired, not the order the
                # leads were seen, and every date question asked of it would still answer the same
                # while the history a member reads told a different story.
                .order_by(
                    SIGHTING_TABLE.c.seen,
                    SIGHTING_TABLE.c.recorded_at,
                    SIGHTING_TABLE.c.slug,
                    SIGHTING_TABLE.c.url,
                )
            )
        ).all()
    return [
        {"seen": r.seen, "slug": r.slug, "title": r.title, "url": r.url, "source": r.source}
        for r in rows
    ]


async def read_covered(ctx: Transactional, series: str) -> list[dict]:
    """Every published row of one series, oldest edition first."""
    check_series(series)
    async with ctx.transaction() as connection:
        rows = (
            await connection.execute(
                sa.select(
                    COVERED_TABLE.c.edition,
                    COVERED_TABLE.c.slug,
                    COVERED_TABLE.c.title,
                    COVERED_TABLE.c.url,
                )
                .where(
                    COVERED_TABLE.c.workspace_id == ctx.workspace_id,
                    COVERED_TABLE.c.series == series,
                )
                .order_by(
                    COVERED_TABLE.c.edition,
                    COVERED_TABLE.c.recorded_at,
                    COVERED_TABLE.c.slug,
                )
            )
        ).all()
    return [
        {"edition": r.edition, "slug": r.slug, "title": r.title, "url": r.url} for r in rows
    ]


def last_seen(rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """The most recent sighting date per lead — the only date staleness may ask about."""
    latest: dict[str, str] = {}
    for row in rows:
        slug, seen = row["slug"], row["seen"]
        if slug not in latest or seen > latest[slug]:
            latest[slug] = seen
    return latest


def fresh(rows: Iterable[Mapping[str, Any]], within_days: int, today: date) -> list[tuple[str, str]]:
    """Leads whose most recent sighting is inside the window, most recently seen first."""
    cutoff = (today - timedelta(days=within_days)).isoformat()
    live = [(slug, seen) for slug, seen in last_seen(rows).items() if seen >= cutoff]
    return sorted(live, key=lambda pair: (pair[1], pair[0]), reverse=True)


def recent_rows(rows: Sequence[Mapping[str, Any]], editions: int) -> list[dict]:
    """Every row belonging to the most recent `editions` distinct edition dates.

    Counted in editions rather than days because a series sets its own cadence: five editions is
    five briefs the reader has seen, whether they fell over one week or three.
    """
    dates = set(sorted({row["edition"] for row in rows}, reverse=True)[:editions])
    return [dict(row) for row in rows if row["edition"] in dates]


def seen_lines(rows: Iterable[Mapping[str, Any]]) -> str:
    """The sightings pool as `seen.py` appended it, so the script still reads what this renders."""
    return "".join(
        json.dumps(
            {
                "seen": row["seen"],
                "slug": row["slug"],
                "title": row["title"],
                "url": row["url"],
                "source": row["source"],
            },
            sort_keys=True,
        )
        + "\n"
        for row in rows
    )


def covered_lines(rows: Iterable[Mapping[str, Any]]) -> str:
    """The covered ledger as `covered.py` appended it."""
    return "".join(
        json.dumps(
            {
                "edition": row["edition"],
                "slug": row["slug"],
                "title": row["title"],
                "url": row["url"],
            },
            sort_keys=True,
        )
        + "\n"
        for row in rows
    )


def seen_projection(series: str) -> str:
    return f"{POOL_DIR}/{check_series(series)}.seen.jsonl"


def covered_projection(series: str) -> str:
    return f"{POOL_DIR}/{check_series(series)}.covered.jsonl"
