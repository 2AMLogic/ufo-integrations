"""The historical record a brief series builds: the sightings pool, the covered ledger and the
coverage state, in tables this extension's own migration owns.

**Why a table and not the workspace file alone.** The file lives at a workspace-relative path, which
resolves against the working directory the turn's carrier starts in — and that is not one place. A
conversation whose `sandbox_handle` is `client:<cwd>` runs on the member's own machine in that
directory; any other conversation gets `workspace_root/<conversation_id>`. So the axis is whether a
conversation is bound to a terminal, not whether a human was watching: several terminal-bound
conversations share one tree, and an unbound one has a tree of its own. One series accumulated one
ledger per tree, each complete-looking and none aware of the others. On the demo deploy the
`agent-runtimes` series had two `covered.jsonl` files of 15 rows each whose 2026-09-28 editions
shared **no story at all** — six rows in each, zero overlap.
The no-repeat rule was being enforced against whichever half the running carrier could see.

A row keyed by `(workspace_id, series, ...)` is reachable identically from every turn in the
workspace, whatever ran it and wherever it started. That is the property the file lacks.

**Why the file survives anyway.** It is the half a member can open. So it stays, as a *projection*:
rendered whole from the tables and landed in the series' own conversation by `jobs.py` — a job
rather than a tool so that the copy follows the series rather than whichever turn last recorded, and
so a record that advanced with no workspace to write to is rendered whole later instead of lost.
Rendering whole rather than appending is what keeps the two from drifting: there is no state in the
file that the tables do not hold.

**The row shapes are the file's, unchanged.** A projected line is byte-identical to the line the
scripts used to append, because the scripts are still the reader a member and a sandbox command use,
and because an old file has to be importable back into the tables — which is how a deploy that
already carries divergent ledgers merges them. `tests/test_projection_shape.py` pins that equality
against the skill's own source rather than trusting this sentence.
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

# These shapes are the skills' own, restated here because a skill script is materialised standalone
# in a sandbox and cannot import this package. `test_projection_shape.py` reads the pattern out of
# `_jsonl_pool.py`, the three date patterns out of their scripts, and the states and reasons out of
# `coverage.py`, and asserts they match — so the duplication is checked rather than trusted. The
# coverage window further down is restated and checked the same way.
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

POOL_DIR = "pulse"
DEFAULT_WITHIN_DAYS = 14
DEFAULT_EDITIONS = 5

READ = "read"
READ_EMPTY = "read-empty"
NOT_READ = "not-read"
COVERAGE_STATES = (READ, READ_EMPTY, NOT_READ)
COVERAGE_REASONS = ("unreachable", "rate-limited", "budget-exhausted", "unauthorized")

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


COVERAGE_TABLE = sa.Table(
    "pulse_ext_coverage",
    _metadata,
    sa.Column("workspace_id", sa.Uuid(), _workspace(), primary_key=True),
    sa.Column("series", sa.Text(), primary_key=True),
    sa.Column("gathered", sa.Text(), primary_key=True),
    sa.Column("source", sa.Text(), primary_key=True),
    sa.Column("state", sa.Text(), nullable=False),
    sa.Column("items", sa.Integer(), nullable=False),
    sa.Column("reason", sa.Text(), nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
)


SERIES_TABLE = sa.Table(
    "pulse_ext_series",
    _metadata,
    sa.Column("workspace_id", sa.Uuid(), _workspace(), primary_key=True),
    sa.Column("series", sa.Text(), primary_key=True),
    sa.Column("conversation_id", sa.Uuid(), nullable=False),
    sa.Column("revision", sa.BigInteger(), nullable=False),
    sa.Column("projected_revision", sa.BigInteger(), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)


class Transactional(Protocol):
    """What a store call needs of its `ExtensionContext`, and nothing more."""

    @property
    def workspace_id(self) -> UUID: ...

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


@dataclass(frozen=True)
class Coverage:
    """One source's answer on one gather: `coverage-honesty`'s state, and what it was.

    The gather's date is the batch's, the way an edition's is, because every source in one call was
    read on one gather — a row that carried its own would let one call straddle two of them.
    """

    source: str
    state: str
    items: int = 0
    reason: str = ""


def check_series(series: str) -> str:
    if not SLUG.fullmatch(series):
        raise ValueError(f"series must be a lowercase hyphenated slug, got {series!r}")
    return series


def check_sighting(row: Sighting) -> Sighting:
    if not DATE.fullmatch(row.seen):
        raise ValueError(f"seen must be YYYY-MM-DD, got {row.seen!r}")
    if not SLUG.fullmatch(row.slug):
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
    if not DATE.fullmatch(edition):
        raise ValueError(f"edition must be YYYY-MM-DD, got {edition!r}")
    if not SLUG.fullmatch(row.slug):
        raise ValueError(f"slug must be a lowercase hyphenated slug, got {row.slug!r}")
    return row


def check_coverage(gathered: str, row: Coverage) -> Coverage:
    """The three states and their four failure reasons, refused where the row is none of them.

    A read with no items is `read-empty`, which is an answer; a not-read row names which of the four
    failures it was. Those are the two distinctions a footer is written from, and a row that blurred
    either would report a source nobody reached as a source with nothing in it.
    """
    if not DATE.fullmatch(gathered):
        raise ValueError(f"gathered must be YYYY-MM-DD, got {gathered!r}")
    if not SLUG.fullmatch(row.source):
        raise ValueError(f"source must be a lowercase hyphenated slug, got {row.source!r}")
    if row.state not in COVERAGE_STATES:
        raise ValueError(f"state must be one of {', '.join(COVERAGE_STATES)}, got {row.state!r}")
    if row.state == NOT_READ:
        if row.reason not in COVERAGE_REASONS:
            raise ValueError(
                f"a not-read source names one of {', '.join(COVERAGE_REASONS)}, got {row.reason!r}"
            )
        if row.items:
            raise ValueError(f"a source that went unread returned no items, got {row.items}")
    else:
        if row.reason:
            raise ValueError(f"{row.state} is an answer and carries no reason, got {row.reason!r}")
        if row.state == READ and row.items < 1:
            raise ValueError("a source read with nothing in it is read-empty, which is an answer")
        if row.state == READ_EMPTY and row.items:
            raise ValueError(f"read-empty is the state for no items, got {row.items}")
    return row


async def _upsert(
    connection: AsyncConnection,
    table: sa.Table,
    key: Mapping[str, Any],
    values: Mapping[str, Any],
) -> None:
    """Write the row whether or not it is already there, without a dialect-specific insert.

    An update that matches nothing is followed by an insert. Two fires racing on one key is not a
    case this needs to win: for a sighting and a covered row both carry the same facts by
    construction — the key is every field that distinguishes one from another — so whichever lands
    second writes what the first did. A coverage row is the one key two writes can disagree under,
    and there the later write is the answer by definition: a source that failed and then answered
    was read that gather.
    """
    where = sa.and_(*(table.c[name] == value for name, value in key.items()))
    updated = await connection.execute(sa.update(table).where(where).values(**values))
    if updated.rowcount == 0:
        await connection.execute(sa.insert(table).values(**key, **values))


async def record_sightings(
    ctx: Transactional,
    series: str,
    rows: Sequence[Sighting],
    now: datetime,
    conversation_id: UUID | None = None,
) -> int:
    """Record what a gather saw. Returns the number of rows written, duplicates included."""
    check_series(series)
    checked = [check_sighting(row) for row in rows]
    async with ctx.transaction() as connection:
        await _touch_series(connection, ctx, series, now, conversation_id)
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
    ctx: Transactional,
    series: str,
    edition: str,
    rows: Sequence[Story],
    now: datetime,
    conversation_id: UUID | None = None,
) -> int:
    """Record what an edition published. Returns the number of rows written."""
    check_series(series)
    checked = [check_story(edition, row) for row in rows]
    async with ctx.transaction() as connection:
        await _touch_series(connection, ctx, series, now, conversation_id)
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


async def record_coverage(
    ctx: Transactional,
    series: str,
    gathered: str,
    rows: Sequence[Coverage],
    now: datetime,
    conversation_id: UUID | None = None,
) -> int:
    """Record what each source returned on one gather. Returns the number of rows written.

    Two attempts at one source inside one gather are one row, and the later one is that gather's
    answer: a source that rate-limited the first attempt and answered the second was read that day.
    The file records both and resolves them on read; this resolves them on write, and
    `coverage.py`'s window aggregates to the same states from either.
    """
    check_series(series)
    checked = [check_coverage(gathered, row) for row in rows]
    async with ctx.transaction() as connection:
        await _touch_series(connection, ctx, series, now, conversation_id)
        for row in checked:
            await _upsert(
                connection,
                COVERAGE_TABLE,
                {
                    "workspace_id": ctx.workspace_id,
                    "series": series,
                    "gathered": gathered,
                    "source": row.source,
                },
                {
                    "state": row.state,
                    "items": row.items,
                    "reason": row.reason,
                    "recorded_at": now,
                },
            )
    return len(checked)


async def _touch_series(
    connection: AsyncConnection,
    ctx: Transactional,
    series: str,
    now: datetime,
    conversation_id: UUID | None,
) -> None:
    """Mark this series advanced, inside the same transaction as the rows that advanced it.

    `revision` moving past `projected_revision` is the only thing that makes the projection job open
    a sandbox, so bumping it anywhere but here would let a write land with no projection to follow —
    or, worse, schedule one for a write that then rolled back.

    It is a counter and not the clock, which is the fix for a real fault rather than a preference. A
    wall-clock watermark is only as monotonic as the clock behind it, and a write stamped earlier
    than an already-recorded projection reads as older than the file: its rows are in the record,
    the series is not due, and nothing brings the projection back for them until some later write
    happens to carry a larger stamp. Reproduced before this changed — two rows recorded, `due_series`
    empty, the file holding neither.

    `conversation_id` is where the projection lands. It is carried on every write rather than set
    once, because a series is where it is currently being worked on: a member who moves a brief to a
    new conversation should get the file there, not in the one they left. A write that does not know
    its conversation leaves the existing binding alone rather than clearing it.

    The update is one statement, so `revision + 1` is evaluated by the engine and no advance is lost
    when two writes race: SQLite serializes writers outright, and Postgres under READ COMMITTED
    blocks the second on the row lock and re-evaluates against the committed value, giving N+2
    rather than both N+1. The *insert* path is the narrower case — two writers finding no row can
    both attempt one, and on Postgres the loser takes a unique violation that rolls its transaction
    back, rows and stamp together. Nothing is half-written, and the retry finds the row and updates
    it.
    """
    where = sa.and_(
        SERIES_TABLE.c.workspace_id == ctx.workspace_id, SERIES_TABLE.c.series == series
    )
    values: dict[str, Any] = {
        "revision": SERIES_TABLE.c.revision + 1,
        "updated_at": now,
    }
    if conversation_id is not None:
        values["conversation_id"] = conversation_id
    updated = await connection.execute(sa.update(SERIES_TABLE).where(where).values(**values))
    if updated.rowcount == 0:
        if conversation_id is None:
            # Nothing to bind the projection to, and a row naming no conversation could never be
            # projected. The record itself is unaffected: the rows land, and the first write that
            # does know its conversation creates this row and the projection follows.
            return
        await connection.execute(
            sa.insert(SERIES_TABLE).values(
                workspace_id=ctx.workspace_id,
                series=series,
                conversation_id=conversation_id,
                revision=1,
                projected_revision=None,
                updated_at=now,
            )
        )


def due_projections() -> sa.Select:
    """The workspaces holding a series whose record has moved since its file was last written.

    This is the select `owner_candidates` runs once per tick, projecting `workspace_id` alone. A job
    that woke for every workspace would open a container per pulse conversation per tick to rewrite
    files nothing had changed — `ConversationFiles.write` opens a sandbox rather than reusing a live
    one, so an unconditional projection is not a cheap no-op.
    """
    return (
        sa.select(SERIES_TABLE.c.workspace_id)
        .where(
            sa.or_(
                SERIES_TABLE.c.projected_revision.is_(None),
                SERIES_TABLE.c.projected_revision < SERIES_TABLE.c.revision,
            )
        )
        .distinct()
    )


async def due_series(ctx: Transactional) -> list[tuple[str, UUID, int]]:
    """The bound workspace's series awaiting a projection, with where to land it and the revision
    the record stood at when this read ran.

    That revision is what the projection is later stamped with — never the revision at marking
    time. A write landing while the files are being rendered would otherwise be marked projected by
    a run that never saw it, and its rows would sit outside the file until something else moved the
    series.
    """
    async with ctx.transaction() as connection:
        rows = (
            await connection.execute(
                sa.select(
                    SERIES_TABLE.c.series,
                    SERIES_TABLE.c.conversation_id,
                    SERIES_TABLE.c.revision,
                )
                .where(
                    SERIES_TABLE.c.workspace_id == ctx.workspace_id,
                    sa.or_(
                        SERIES_TABLE.c.projected_revision.is_(None),
                        SERIES_TABLE.c.projected_revision < SERIES_TABLE.c.revision,
                    ),
                )
                .order_by(SERIES_TABLE.c.series)
            )
        ).all()
    return [(r.series, _as_uuid(r.conversation_id), r.revision) for r in rows]


async def mark_projected(ctx: Transactional, series: str, through: int) -> None:
    """Record that the files carry this series' record as far as revision `through`.

    Guarded on `projected_revision < through` so a slow run cannot drag the mark backwards past a
    newer projection that already overtook it — which would send the next tick to re-render a file
    that was already current, forever, for as long as two runs kept overlapping.
    """
    async with ctx.transaction() as connection:
        await connection.execute(
            sa.update(SERIES_TABLE)
            .where(
                SERIES_TABLE.c.workspace_id == ctx.workspace_id,
                SERIES_TABLE.c.series == series,
                sa.or_(
                    SERIES_TABLE.c.projected_revision.is_(None),
                    SERIES_TABLE.c.projected_revision < through,
                ),
            )
            .values(projected_revision=through)
        )


def _as_uuid(value: Any) -> UUID:
    """SQLite hands a `Uuid` column back as text on a connection core did not type for us."""
    return value if isinstance(value, UUID) else UUID(str(value))


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


async def read_coverage(ctx: Transactional, series: str) -> list[dict]:
    """Every source state one series has recorded, oldest gather first.

    One row per source per gather, which is what the window aggregates: a source's three days read
    as one source across three gathers, and a gather no source recorded a state on is not a gather.
    """
    check_series(series)
    async with ctx.transaction() as connection:
        rows = (
            await connection.execute(
                sa.select(
                    COVERAGE_TABLE.c.gathered,
                    COVERAGE_TABLE.c.source,
                    COVERAGE_TABLE.c.state,
                    # By key, not by attribute: `.c.items` is `ColumnCollection.items`, the
                    # method, and passing that as a select column raises at execution time rather
                    # than here. The column keeps the name the file's field has, because that name
                    # is what the projection renders; the row it comes back on has no such method,
                    # so `r.items` below is the column.
                    COVERAGE_TABLE.c["items"],
                    COVERAGE_TABLE.c.reason,
                )
                .where(
                    COVERAGE_TABLE.c.workspace_id == ctx.workspace_id,
                    COVERAGE_TABLE.c.series == series,
                )
                .order_by(
                    COVERAGE_TABLE.c.gathered,
                    COVERAGE_TABLE.c.recorded_at,
                    COVERAGE_TABLE.c.source,
                )
            )
        ).all()
    return [
        {
            "gathered": r.gathered,
            "source": r.source,
            "state": r.state,
            "items": r.items,
            "reason": r.reason,
        }
        for r in rows
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


# The window and its lines are `coverage.py`'s, restated for the same reason the shapes above are:
# `pulse_recall` answers a footer from the record in any conversation, and `coverage.py window`
# answers it from one tree's copy. `test_projection_shape.py` runs both over the same rows and
# asserts they say the same thing, so a footer does not depend on which of the two was read.


def _inside(gathered: str, since: str, until: str) -> bool:
    return (not since or gathered >= since) and (not until or gathered <= until)


def coverage_gathers(rows: Iterable[Mapping[str, Any]], since: str, until: str) -> list[str]:
    """The distinct gather dates inside the window, oldest first: the denominator of every count.
    A gather that recorded no source state is not one of them."""
    return sorted({row["gathered"] for row in rows if _inside(row["gathered"], since, until)})


def coverage_window(rows: Sequence[Mapping[str, Any]], since: str, until: str) -> list[dict]:
    """Every source's states across the gathers in the window, by source slug — the counts that
    separate "unread on two of three" from "unread throughout" and from "read every gather"."""
    dates = set(coverage_gathers(rows, since, until))
    answers: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        if row["gathered"] in dates:
            answers.setdefault(row["source"], {})[row["gathered"]] = row

    aggregates = []
    for source in sorted(answers):
        states = list(answers[source].values())
        reasons: dict[str, int] = {}
        for row in states:
            if row["state"] == NOT_READ:
                reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
        aggregates.append(
            {
                "source": source,
                "gathers": len(dates),
                "states": {s: sum(row["state"] == s for row in states) for s in COVERAGE_STATES},
                "unrecorded": len(dates) - len(states),
                "items": sum(row["items"] for row in states),
                "reasons": dict(sorted(reasons.items(), key=lambda pair: (-pair[1], pair[0]))),
            }
        )
    return aggregates


def _reasons_of(aggregate: Mapping[str, Any]) -> str:
    reasons = aggregate["reasons"]
    if len(reasons) == 1:
        return next(iter(reasons))
    return ", ".join(f"{reason} ({count})" for reason, count in reasons.items())


def _of(count: int, total: int) -> str:
    return f"all {total} gathers" if count == total else f"{count} of {total} gathers"


def _items(count: int) -> str:
    return f"{count} item" if count == 1 else f"{count} items"


def coverage_line(aggregate: Mapping[str, Any]) -> str:
    """One source's state across the window, in the words a footer is written from. A window of
    one gather reads as one run; a longer one says how many of its gathers each state held."""
    total, states = aggregate["gathers"], aggregate["states"]
    if total == 1:
        if states[NOT_READ]:
            return f"not read — {_reasons_of(aggregate)}"
        if states[READ]:
            return f"read ({_items(aggregate['items'])})"
        return "read, nothing in it"

    segments = []
    answered = states[READ] + states[READ_EMPTY]
    if answered:
        empty = ", nothing in it" if answered == 1 else ", nothing in them"
        found = f" ({_items(aggregate['items'])})" if aggregate["items"] else empty
        segments.append(f"read on {_of(answered, total)}{found}")
    if states[NOT_READ]:
        segments.append(f"not read on {_of(states[NOT_READ], total)} — {_reasons_of(aggregate)}")
    if aggregate["unrecorded"]:
        segments.append(f"no state recorded on {_of(aggregate['unrecorded'], total)}")
    return "; ".join(segments)


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


def coverage_lines(rows: Iterable[Mapping[str, Any]]) -> str:
    """The coverage state as `coverage.py` appended it."""
    return "".join(
        json.dumps(
            {
                "gathered": row["gathered"],
                "source": row["source"],
                "state": row["state"],
                "items": row["items"],
                "reason": row["reason"],
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


def coverage_projection(series: str) -> str:
    return f"{POOL_DIR}/{check_series(series)}.coverage.jsonl"
