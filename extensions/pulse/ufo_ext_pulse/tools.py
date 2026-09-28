"""The three calls that make a brief's record survive a fire nobody is watching.

Two write, one reads. They exist because the skills' own scripts cannot run without a client
carrying a command tool, and the fire a recurring brief actually runs on carries none — so every
gather and every edition recorded nothing on the path the product is built around (#120).

Each write lands its rows in this extension's tables and then *projects* the whole series to the
workspace file the scripts and the member read. The projection is best effort and says so in its
own result line: a fire with no carrier attached has no workspace to land a file in, and that is
the normal case rather than a failure. The table write is the one that must not fail quietly, so it
is not wrapped — a broken store raises and the turn hears about it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ufo.sdk.tools import TextContent, ToolContext, ToolResult
from ufo_ext_pulse import record
from ufo_ext_pulse.record import Sighting, Story

RECORD_SIGHTINGS_TOOL = "pulse_record_sightings"
RECORD_EDITION_TOOL = "pulse_record_edition"
RECALL_TOOL = "pulse_recall"

NO_WORKSPACE = "no workspace file written: nothing is carrying one on this fire"


class SightingInput(BaseModel):
    seen: str = Field(description="The date this lead was seen, YYYY-MM-DD.")
    slug: str = Field(description="The lead's stable identity, lowercase and hyphenated.")
    title: str = Field(description="The headline as this sighting states it.")
    url: str = Field(description="The address this sighting was found at. Required.")
    source: str = Field(default="", description="Where it was read: a feed, a site, a forum.")


class StoryInput(BaseModel):
    slug: str = Field(description="The story's stable identity, lowercase and hyphenated.")
    title: str = Field(description="The headline the edition carried.")
    url: str = Field(default="", description="The address the edition cited.")


class RecordSightingsInput(BaseModel):
    series: str = Field(description="The brief series, lowercase and hyphenated.")
    sightings: list[SightingInput] = Field(
        description="Every lead this gather surfaced, published or not. Send them in one call."
    )


class RecordEditionInput(BaseModel):
    series: str = Field(description="The brief series, lowercase and hyphenated.")
    edition: str = Field(description="The edition's date, YYYY-MM-DD.")
    stories: list[StoryInput] = Field(description="Every story this edition carried.")


class RecallInput(BaseModel):
    series: str = Field(description="The brief series, lowercase and hyphenated.")
    within_days: int = Field(
        default=record.DEFAULT_WITHIN_DAYS,
        description="How recently a lead must have been seen to count as live.",
    )
    editions: int = Field(
        default=record.DEFAULT_EDITIONS,
        description="How many past editions the no-repeat rule reads back over.",
    )
    slug: str | None = Field(
        default=None,
        description=(
            "One lead. Given, the answer is that lead's whole sighting history and every edition "
            "that carried it, which is the evidence a material new development needs. Omitted, "
            "the answer is the live leads and what the recent editions covered."
        ),
    )


def _said(text: str, *, error: bool = False) -> ToolResult:
    return ToolResult(content=(TextContent(text=text),), is_error=error)


def _ext(ctx: ToolContext, tool: str):
    ext = ctx.ext
    if ext is None:
        raise RuntimeError(f"{tool} dispatched without its ExtensionContext")
    return ext


async def _project(ctx: ToolContext, ext, series: str) -> str:
    """Render both files whole from the tables and land them where a member can open them.

    Whole rather than appended: the table is the only state, so a projection written after three
    unwatched fires simply catches up, and there is no path by which the file and the table can
    disagree about a row. A conversation with no live sandbox cannot take a file, which is exactly
    what an unattended fire looks like — so that is reported, not raised.
    """
    if ext.files is None:
        return NO_WORKSPACE
    conversation_id: UUID = ctx.turn.conversation_id
    seen = record.seen_lines(await record.read_sightings(ext, series))
    covered = record.covered_lines(await record.read_covered(ext, series))
    try:
        await ext.files.write(conversation_id, record.seen_projection(series), seen.encode())
        await ext.files.write(conversation_id, record.covered_projection(series), covered.encode())
    except Exception as failure:  # noqa: BLE001 - the record is written; the copy of it is not
        return f"no workspace file written ({type(failure).__name__}: {failure})"
    return f"workspace files updated: {record.seen_projection(series)} and its covered ledger"


async def record_sightings(ctx: ToolContext, args: RecordSightingsInput) -> ToolResult:
    """Record every lead a gather surfaced, whether or not an edition will carry it."""
    ext = _ext(ctx, RECORD_SIGHTINGS_TOOL)
    if not args.sightings:
        return _said("No sightings given. A gather that found nothing records nothing.", error=True)
    rows = [
        Sighting(seen=s.seen, slug=s.slug, title=s.title, url=s.url, source=s.source)
        for s in args.sightings
    ]
    written = await record.record_sightings(ext, args.series, rows, datetime.now(UTC))
    return _said(
        f"recorded {written} sighting{'' if written == 1 else 's'} in {args.series}. "
        f"{await _project(ctx, ext, args.series)}"
    )


async def record_edition(ctx: ToolContext, args: RecordEditionInput) -> ToolResult:
    """Record what an edition published, so the next one knows what it may not repeat."""
    ext = _ext(ctx, RECORD_EDITION_TOOL)
    if not args.stories:
        return _said(
            "No stories given. An edition that carried nothing still carried a window — say so in "
            "the brief; the ledger records stories.",
            error=True,
        )
    rows = [Story(slug=s.slug, title=s.title, url=s.url) for s in args.stories]
    written = await record.record_covered(
        ext, args.series, args.edition, rows, datetime.now(UTC)
    )
    return _said(
        f"recorded {written} stor{'y' if written == 1 else 'ies'} in {args.series} "
        f"edition {args.edition}. {await _project(ctx, ext, args.series)}"
    )


async def recall(ctx: ToolContext, args: RecallInput) -> ToolResult:
    """Read the record back: what is live, what is spent, or one lead's whole history."""
    ext = _ext(ctx, RECALL_TOOL)
    sightings = await record.read_sightings(ext, args.series)
    covered = await record.read_covered(ext, args.series)

    if args.slug is not None:
        history = [row for row in sightings if row["slug"] == args.slug]
        carried = [row for row in covered if row["slug"] == args.slug]
        if not history and not carried:
            return _said(f"{args.slug}: never seen and never carried in {args.series}.")
        lines = [f"{args.slug} in {args.series}"]
        lines += [
            f"  seen {row['seen']}  {row['title']}"
            + (f"  [{row['source']}]" if row["source"] else "")
            for row in history
        ] or ["  never seen"]
        lines += [f"  carried {row['edition']}  {row['title']}" for row in carried] or [
            "  never carried"
        ]
        return _said("\n".join(lines))

    live = record.fresh(sightings, args.within_days, datetime.now(UTC).date())
    titles = {row["slug"]: row["title"] for row in sightings}
    spent = record.recent_rows(covered, args.editions)
    lines = [
        f"{len(sightings)} sighting{'' if len(sightings) == 1 else 's'} on record in "
        f"{args.series}; {len(live)} lead{'' if len(live) == 1 else 's'} seen in the last "
        f"{args.within_days} days."
    ]
    lines += [f"  live  {seen}  {slug}  {titles.get(slug, '')}" for slug, seen in live] or [
        "  no lead has been seen inside the window"
    ]
    lines.append(
        f"Carried in the last {args.editions} edition"
        f"{'' if args.editions == 1 else 's'} — ineligible without a material new development:"
    )
    lines += [f"  {row['edition']}  {row['slug']}  {row['title']}" for row in spent] or [
        "  nothing; no edition has been recorded"
    ]
    return _said("\n".join(lines))
