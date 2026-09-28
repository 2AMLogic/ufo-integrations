"""The record in the tables pulse owns, and the workspace files projected from it.

The property every one of these exists for is the one #120 named: **a fire with no carrier still
records.** So the carrier here is a thing that can be absent or broken, and the assertions about a
row never depend on a file having landed.

Skipped without `ufo`, whose distribution carries sqlalchemy; the file-shaped contract tests beside
this one still run on a checkout that has neither.
"""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy", reason="install ufo from git to run the store tests")

from pulse_fakes import Files, Store, on_store, tool_context  # noqa: E402
from ufo_ext_pulse import record, tools  # noqa: E402
from ufo_ext_pulse.record import Sighting, Story  # noqa: E402

NOW = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
SERIES = "data-infra"


def sighting(seen: str, slug: str, title: str = "Acme 1.0", url: str = "https://x/1") -> Sighting:
    return Sighting(seen=seen, slug=slug, title=title, url=url, source="releases")


# --- the record itself -------------------------------------------------------------------------


@on_store
async def test_an_unrecorded_series_reads_empty(store: Store) -> None:
    assert await record.read_sightings(store, SERIES) == []
    assert await record.read_covered(store, SERIES) == []


@on_store
async def test_a_sighting_is_read_back_whole(store: Store) -> None:
    await record.record_sightings(store, SERIES, [sighting("2026-09-21", "acme-1-0")], NOW)
    assert await record.read_sightings(store, SERIES) == [
        {
            "seen": "2026-09-21",
            "slug": "acme-1-0",
            "title": "Acme 1.0",
            "url": "https://x/1",
            "source": "releases",
        }
    ]


@on_store
async def test_the_same_sighting_recorded_twice_is_one_row(store: Store) -> None:
    """The property a file could not have: a replayed fire, a retried batch, or a gather that
    surfaced one lead twice lands one row. An append-only file would have held both and every
    count read off it would have been wrong by however many times the fire was retried."""
    for _ in range(3):
        await record.record_sightings(store, SERIES, [sighting("2026-09-21", "acme-1-0")], NOW)
    assert len(await record.read_sightings(store, SERIES)) == 1


@on_store
async def test_a_second_sighting_of_one_lead_on_a_later_day_is_a_second_row(store: Store) -> None:
    """Two rows, not an overwrite: the difference between them is the evidence a material new
    development needs."""
    await record.record_sightings(
        store, SERIES, [sighting("2026-09-21", "acme-1-0", "Acme 1.0 in beta")], NOW
    )
    await record.record_sightings(
        store, SERIES, [sighting("2026-09-23", "acme-1-0", "Acme 1.0 GA")], NOW
    )
    rows = await record.read_sightings(store, SERIES)
    assert [row["seen"] for row in rows] == ["2026-09-21", "2026-09-23"]
    assert rows[0]["title"] != rows[1]["title"]


@on_store
async def test_one_lead_at_two_addresses_on_one_day_is_two_rows(store: Store) -> None:
    """The url is in the key, so the pool keeps what `reconcile` exists to ask about rather than
    collapsing it into one row and answering the question itself."""
    await record.record_sightings(
        store,
        SERIES,
        [
            sighting("2026-09-21", "acme-1-0", url="https://x/blog"),
            sighting("2026-09-21", "acme-1-0", url="https://x/notes"),
        ],
        NOW,
    )
    assert len({row["url"] for row in await record.read_sightings(store, SERIES)}) == 2


@on_store
async def test_a_retitled_sighting_keeps_one_row_and_the_newer_title(store: Store) -> None:
    await record.record_sightings(store, SERIES, [sighting("2026-09-21", "acme-1-0", "first")], NOW)
    await record.record_sightings(store, SERIES, [sighting("2026-09-21", "acme-1-0", "second")], NOW)
    rows = await record.read_sightings(store, SERIES)
    assert [row["title"] for row in rows] == ["second"]


@on_store
async def test_a_blank_url_is_refused_and_writes_nothing(store: Store) -> None:
    """Blank is as unreconcilable as missing, and it is also part of the key — every whitespace-only
    sighting of a lead would otherwise collapse into one row."""
    with pytest.raises(ValueError):
        await record.record_sightings(
            store, SERIES, [Sighting("2026-09-21", "acme-1-0", "Acme", "   ", "")], NOW
        )
    assert await record.read_sightings(store, SERIES) == []


@on_store
async def test_a_bad_date_or_slug_is_refused_and_writes_nothing(store: Store) -> None:
    with pytest.raises(ValueError):
        await record.record_sightings(store, SERIES, [sighting("21 Sep 2026", "acme-1-0")], NOW)
    with pytest.raises(ValueError):
        await record.record_sightings(store, SERIES, [sighting("2026-09-21", "Acme 1.0")], NOW)
    assert await record.read_sightings(store, SERIES) == []


@on_store
async def test_a_whole_batch_is_refused_when_one_row_is_bad(store: Store) -> None:
    """A gather never lands half of itself: one bad row and the batch writes nothing.

    Two things hold this, and only the outcome is asserted because this cannot tell them apart.
    `record_sightings` checks every row before opening a transaction, and the transaction would
    roll back a partial write anyway — moving the check inside the write loop leaves this test
    green, which is measured (M2) rather than assumed. Stating it here so the next reader does not
    take the test as evidence that the ordering is what does the work.
    """
    with pytest.raises(ValueError):
        await record.record_sightings(
            store,
            SERIES,
            [sighting("2026-09-21", "acme-1-0"), sighting("2026-09-21", "Bad Slug")],
            NOW,
        )
    assert await record.read_sightings(store, SERIES) == []


@on_store
async def test_a_series_name_cannot_escape(store: Store) -> None:
    with pytest.raises(ValueError):
        await record.read_sightings(store, "../escape")
    with pytest.raises(ValueError):
        record.seen_projection("../escape")


@on_store
async def test_one_series_never_reads_another(store: Store) -> None:
    await record.record_sightings(store, SERIES, [sighting("2026-09-21", "acme-1-0")], NOW)
    await record.record_sightings(store, "open-silicon", [sighting("2026-09-21", "beta-2")], NOW)
    assert [row["slug"] for row in await record.read_sightings(store, SERIES)] == ["acme-1-0"]


@on_store
async def test_one_workspace_never_reads_another(store: Store) -> None:
    """The scoping is in the predicate. Two workspaces sharing one database and one series name see
    only their own rows — the case a store keyed by series alone would have got wrong silently."""
    other = Store(engine=store.engine, workspace_id=uuid4())
    await record.record_sightings(store, SERIES, [sighting("2026-09-21", "acme-1-0")], NOW)
    await record.record_sightings(other, SERIES, [sighting("2026-09-21", "beta-2")], NOW)
    assert [row["slug"] for row in await record.read_sightings(store, SERIES)] == ["acme-1-0"]
    assert [row["slug"] for row in await record.read_sightings(other, SERIES)] == ["beta-2"]


@on_store
async def test_reading_the_pool_never_changes_it(store: Store) -> None:
    """Collection is additive. The moment a read writes, staleness has become the expiry the
    design rules out."""
    await record.record_sightings(store, SERIES, [sighting("2026-08-01", "acme-1-0")], NOW)
    rows = await record.read_sightings(store, SERIES)
    record.fresh(rows, 14, date(2026, 9, 28))
    record.last_seen(rows)
    assert await record.read_sightings(store, SERIES) == rows


# --- what is live --------------------------------------------------------------------------------


def test_freshness_keys_on_the_most_recent_sighting() -> None:
    """A lead first seen thirty days ago and seen again this morning is live, not old."""
    rows = [
        {"seen": "2026-08-20", "slug": "acme-1-0"},
        {"seen": "2026-09-28", "slug": "acme-1-0"},
        {"seen": "2026-08-20", "slug": "quiet-one"},
    ]
    assert record.fresh(rows, 14, date(2026, 9, 28)) == [("acme-1-0", "2026-09-28")]


def test_a_stale_lead_is_kept_and_simply_not_offered() -> None:
    """Age is a reason not to pursue a lead, never a reason to forget it."""
    rows = [{"seen": "2026-01-01", "slug": "quiet-one"}]
    assert record.fresh(rows, 14, date(2026, 9, 28)) == []
    assert record.last_seen(rows) == {"quiet-one": "2026-01-01"}


def test_recent_rows_counts_editions_not_days() -> None:
    """Five editions is five briefs the reader has seen, whether they fell over one week or three."""
    rows = [
        {"edition": "2026-01-01", "slug": "old"},
        {"edition": "2026-09-01", "slug": "mid"},
        {"edition": "2026-09-28", "slug": "new"},
    ]
    assert [row["slug"] for row in record.recent_rows(rows, 2)] == ["mid", "new"]
    assert [row["slug"] for row in record.recent_rows(rows, 5)] == ["old", "mid", "new"]


# --- the covered ledger --------------------------------------------------------------------------


@on_store
async def test_one_edition_carries_a_story_once(store: Store) -> None:
    for _ in range(3):
        await record.record_covered(
            store, SERIES, "2026-09-28", [Story("acme-1-0", "Acme 1.0", "https://x/1")], NOW
        )
    assert len(await record.read_covered(store, SERIES)) == 1


@on_store
async def test_a_story_carried_again_is_a_row_in_each_edition(store: Store) -> None:
    """The material-new-development exception, as the ledger has always recorded it."""
    await record.record_covered(store, SERIES, "2026-09-21", [Story("acme-1-0", "beta")], NOW)
    await record.record_covered(store, SERIES, "2026-09-28", [Story("acme-1-0", "GA")], NOW)
    rows = await record.read_covered(store, SERIES)
    assert [row["edition"] for row in rows] == ["2026-09-21", "2026-09-28"]


@on_store
async def test_a_bad_edition_date_is_refused_and_writes_nothing(store: Store) -> None:
    with pytest.raises(ValueError):
        await record.record_covered(store, SERIES, "28 Sep", [Story("acme-1-0", "Acme")], NOW)
    assert await record.read_covered(store, SERIES) == []


# --- the projection ------------------------------------------------------------------------------


@on_store
async def test_a_write_projects_both_files_when_a_carrier_can_take_them(store: Store) -> None:
    ctx = tool_context(store)
    result = await tools.record_sightings(
        ctx,
        tools.RecordSightingsInput(
            series=SERIES,
            sightings=[
                tools.SightingInput(
                    seen="2026-09-21", slug="acme-1-0", title="Acme 1.0", url="https://x/1"
                )
            ],
        ),
    )
    assert not result.is_error
    files = store.files
    assert set(files.written) == {"pulse/data-infra.seen.jsonl", "pulse/data-infra.covered.jsonl"}
    assert '"slug": "acme-1-0"' in files.text("pulse/data-infra.seen.jsonl")


@on_store
async def test_a_fire_with_no_carrier_still_records(store: Store) -> None:
    """The whole of #120 in one test. A scheduled fire has no client and therefore no workspace to
    land a file in; the row goes to the table regardless, and the result says which half happened
    rather than reporting a clean success over a record that was never written."""
    store.files = None
    result = await tools.record_sightings(
        tool_context(store),
        tools.RecordSightingsInput(
            series=SERIES,
            sightings=[
                tools.SightingInput(
                    seen="2026-09-21", slug="acme-1-0", title="Acme 1.0", url="https://x/1"
                )
            ],
        ),
    )
    assert not result.is_error
    assert tools.NO_WORKSPACE in result.content[0].text
    assert len(await record.read_sightings(store, SERIES)) == 1


@on_store
async def test_a_broken_carrier_loses_the_file_and_keeps_the_row(store: Store) -> None:
    store.files = Files(breaks=True)
    result = await tools.record_sightings(
        tool_context(store),
        tools.RecordSightingsInput(
            series=SERIES,
            sightings=[
                tools.SightingInput(
                    seen="2026-09-21", slug="acme-1-0", title="Acme 1.0", url="https://x/1"
                )
            ],
        ),
    )
    assert "no workspace file written" in result.content[0].text
    assert len(await record.read_sightings(store, SERIES)) == 1


@on_store
async def test_a_projection_after_unwatched_fires_catches_the_whole_file_up(store: Store) -> None:
    """Rendered whole rather than appended, so there is no path by which the file and the table can
    disagree about a row — three fires nobody saw are three lines the next projection carries."""
    store.files = None
    for day in ("2026-09-21", "2026-09-22", "2026-09-23"):
        await record.record_sightings(store, SERIES, [sighting(day, f"acme-{day[-2:]}")], NOW)
    store.files = Files()
    await tools.record_sightings(
        tool_context(store),
        tools.RecordSightingsInput(
            series=SERIES,
            sightings=[
                tools.SightingInput(
                    seen="2026-09-24", slug="acme-24", title="Acme", url="https://x/1"
                )
            ],
        ),
    )
    assert store.files.text("pulse/data-infra.seen.jsonl").count("\n") == 4


@on_store
async def test_an_empty_batch_is_refused_rather_than_reported_as_a_write(store: Store) -> None:
    result = await tools.record_sightings(
        tool_context(store), tools.RecordSightingsInput(series=SERIES, sightings=[])
    )
    assert result.is_error


# --- recall ---------------------------------------------------------------------------------------


@on_store
async def test_recall_names_the_live_leads_and_what_the_editions_spent(store: Store) -> None:
    today = datetime.now(UTC).date().isoformat()
    await record.record_sightings(store, SERIES, [sighting(today, "acme-1-0")], NOW)
    await record.record_covered(store, SERIES, today, [Story("beta-2", "Beta 2")], NOW)
    said = (
        await tools.recall(tool_context(store), tools.RecallInput(series=SERIES))
    ).content[0].text
    assert "acme-1-0" in said
    assert "beta-2" in said


@on_store
async def test_recall_of_one_slug_answers_with_its_whole_history(store: Store) -> None:
    await record.record_sightings(
        store, SERIES, [sighting("2026-09-21", "acme-1-0", "beta")], NOW
    )
    await record.record_sightings(store, SERIES, [sighting("2026-09-23", "acme-1-0", "GA")], NOW)
    await record.record_covered(store, SERIES, "2026-09-23", [Story("acme-1-0", "GA")], NOW)
    said = (
        await tools.recall(tool_context(store), tools.RecallInput(series=SERIES, slug="acme-1-0"))
    ).content[0].text
    assert "beta" in said and "GA" in said and "carried 2026-09-23" in said


@on_store
async def test_recall_of_an_unknown_slug_says_so_rather_than_answering_emptily(store: Store) -> None:
    said = (
        await tools.recall(tool_context(store), tools.RecallInput(series=SERIES, slug="nobody"))
    ).content[0].text
    assert "never seen and never carried" in said


@on_store
async def test_recall_never_changes_the_record(store: Store) -> None:
    await record.record_sightings(store, SERIES, [sighting("2026-09-21", "acme-1-0")], NOW)
    before = await record.read_sightings(store, SERIES)
    await tools.recall(tool_context(store), tools.RecallInput(series=SERIES))
    await tools.recall(tool_context(store), tools.RecallInput(series=SERIES, slug="acme-1-0"))
    assert await record.read_sightings(store, SERIES) == before
