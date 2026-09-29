"""The projection is the file the scripts wrote, byte for byte.

`record.py` restates the shapes the skill scripts own — the slug pattern, the three date patterns,
and coverage's three states with their four reasons — because a skill script is materialised
standalone in a sandbox and cannot import the extension package. Restating is not the risk;
restating *and then drifting* is, because the drift would be silent: a store that accepted a slug
the script rejects writes a line the script cannot read back, and the member's file and the agent's
record would disagree about what the series holds.

So these read the scripts' own source and behaviour rather than trusting the duplication. They are
the reason `record.py` may say "the row shapes are the file's, unchanged" in its docstring.

Skipped without sqlalchemy, which is `record.py`'s only import beyond the standard library.
"""

import json

import pytest

pytest.importorskip("sqlalchemy", reason="install ufo from git to run the projection tests")

from ufo_ext_pulse import record  # noqa: E402

ROW = {
    "seen": "2026-09-21",
    "slug": "acme-1-0",
    "title": "Acme 1.0",
    "url": "https://x/1",
    "source": "releases",
}
STORY = {"edition": "2026-09-28", "slug": "acme-1-0", "title": "Acme 1.0", "url": "https://x/1"}
STATE = {
    "gathered": "2026-09-24",
    "source": "filings-index",
    "state": "not-read",
    "items": 0,
    "reason": "rate-limited",
}


def test_the_pool_patterns_are_the_scripts_own(seen) -> None:
    assert record.SLUG.pattern == seen.SLUG.pattern
    assert record.DATE.pattern == seen.SEEN_DATE.pattern
    assert record.POOL_DIR == seen.POOL_DIR
    assert record.DEFAULT_WITHIN_DAYS == seen.DEFAULT_WITHIN_DAYS


def test_the_ledger_patterns_are_the_scripts_own(covered) -> None:
    assert record.DATE.pattern == covered.EDITION.pattern
    assert record.POOL_DIR == covered.LEDGER_DIR
    assert record.DEFAULT_EDITIONS == covered.DEFAULT_EDITIONS


def test_the_coverage_patterns_and_vocabulary_are_the_scripts_own(coverage) -> None:
    """The states and the reasons are a vocabulary rather than a format, and a store that accepted
    a fourth state would write a line the window aggregates into no column at all."""
    assert record.DATE.pattern == coverage.GATHERED.pattern
    assert record.POOL_DIR == coverage.COVERAGE_DIR
    assert record.COVERAGE_STATES == coverage.STATES
    assert record.COVERAGE_REASONS == coverage.REASONS


@pytest.mark.parametrize(
    "row",
    [
        ("2026-09-24", "releases", "read", 11, ""),
        ("2026-09-24", "forums", "read-empty", 0, ""),
        ("2026-09-24", "filings-index", "not-read", 0, "rate-limited"),
        ("Thursday", "releases", "read", 11, ""),
        ("2026-09-24", "The Filings Index", "read", 11, ""),
        ("2026-09-24", "releases", "partial", 11, ""),
        ("2026-09-24", "releases", "read", 0, ""),
        ("2026-09-24", "forums", "read-empty", 3, ""),
        ("2026-09-24", "releases", "read", 11, "rate-limited"),
        ("2026-09-24", "filings-index", "not-read", 0, ""),
        ("2026-09-24", "filings-index", "not-read", 0, "slow"),
        ("2026-09-24", "filings-index", "not-read", 3, "unreachable"),
    ],
)
def test_the_two_validators_agree_on_every_row(coverage, row: tuple) -> None:
    """The duplication checked rather than trusted, in the direction that matters: a row the script
    writes and the store refuses cannot be imported, and a row the store takes and the script
    rejects is a line the member's own reader stops at."""
    gathered, source, state, items, reason = row

    def refused(call) -> bool:
        try:
            call()
        except ValueError:
            return True
        return False

    by_script = refused(
        lambda: coverage.record("data-infra", gathered, source, state, items, reason)
    )
    by_store = refused(
        lambda: record.check_coverage(
            gathered, record.Coverage(source, state, items, reason)
        )
    )
    assert by_script == by_store


WINDOW = [
    ("2026-09-22", "releases", "read", 4, ""),
    ("2026-09-22", "filings-index", "not-read", 0, "rate-limited"),
    ("2026-09-22", "forums", "read-empty", 0, ""),
    ("2026-09-23", "releases", "read", 1, ""),
    ("2026-09-23", "filings-index", "not-read", 0, "unreachable"),
    ("2026-09-24", "releases", "read-empty", 0, ""),
    ("2026-09-24", "filings-index", "not-read", 0, "rate-limited"),
    ("2026-09-25", "papers", "read", 2, ""),
]


@pytest.mark.parametrize(
    ("since", "until"),
    [("", ""), ("2026-09-22", "2026-09-24"), ("2026-09-23", ""), ("2026-09-25", "2026-09-25")],
)
def test_the_tool_and_the_script_write_one_footer(coverage, since: str, until: str) -> None:
    """The window is restated too, and a footer must not depend on which of the two was read: the
    member's terminal and the member's conversation would otherwise disagree about one gather."""
    for row in WINDOW:
        coverage.record("data-infra", *row)
    rows = coverage.read_rows("data-infra")

    gathers = coverage.gathers("data-infra", since, until)
    assert record.coverage_gathers(rows, since, until) == gathers
    by_store = record.coverage_window(rows, since, until)
    assert by_store == coverage.window("data-infra", since, until)
    assert [record.coverage_line(a) for a in by_store] == [
        coverage.state_line(a) for a in by_store
    ]


def test_a_projected_sighting_line_is_the_line_the_script_appends(seen) -> None:
    """Not a comparison of formats — the script writes a real file here, and the projection of the
    same row has to be that file's bytes."""
    path = seen.record(
        "data-infra", ROW["seen"], ROW["slug"], ROW["title"], ROW["url"], ROW["source"]
    )
    assert record.seen_lines([ROW]) == path.read_text()


def test_a_projected_ledger_line_is_the_line_the_script_appends(covered) -> None:
    path = covered.record(
        "data-infra", STORY["edition"], STORY["slug"], STORY["title"], STORY["url"]
    )
    assert record.covered_lines([STORY]) == path.read_text()


def test_a_projected_coverage_line_is_the_line_the_script_appends(coverage) -> None:
    path = coverage.record(
        "data-infra",
        STATE["gathered"],
        STATE["source"],
        STATE["state"],
        STATE["items"],
        STATE["reason"],
    )
    assert record.coverage_lines([STATE]) == path.read_text()


def test_the_script_reads_a_whole_coverage_projection_back_unchanged(coverage) -> None:
    """The footer's own reader over the store's writer: `window` has to aggregate what the
    projection renders, or a multi-gather footer counts days the record does not hold."""
    rows = [
        dict(STATE, gathered="2026-09-24"),
        dict(STATE, gathered="2026-09-25", source="releases", state="read", items=4, reason=""),
        dict(STATE, gathered="2026-09-25"),
    ]
    path = coverage.coverage_path("data-infra")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.coverage_lines(rows))
    assert coverage.read_rows("data-infra") == rows
    assert coverage.gathers("data-infra") == ["2026-09-24", "2026-09-25"]
    filings = next(a for a in coverage.window("data-infra") if a["source"] == "filings-index")
    assert filings["states"]["not-read"] == 2


def test_the_script_reads_a_whole_projection_back_unchanged(seen, tmp_path) -> None:
    """The member's reader over the agent's writer: whatever the store renders, `seen.py` parses to
    the rows the store holds, so `fresh`, `stale` and `history` answer the same on either side."""
    rows = [
        dict(ROW, seen="2026-09-21"),
        dict(ROW, seen="2026-09-23", title="Acme 1.0 GA"),
        dict(ROW, seen="2026-09-23", slug="beta-2", url="https://x/2"),
    ]
    path = seen.pool_path("data-infra")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.seen_lines(rows))
    assert seen.read_rows("data-infra") == rows


def test_the_script_reads_a_whole_ledger_projection_back_unchanged(covered) -> None:
    rows = [dict(STORY, edition="2026-09-21"), dict(STORY, edition="2026-09-28")]
    path = covered.ledger_path("data-infra")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.covered_lines(rows))
    assert covered.read_rows("data-infra") == rows


def test_the_projection_paths_are_the_paths_the_scripts_resolve(seen, covered, coverage) -> None:
    assert record.seen_projection("data-infra") == str(seen.pool_path("data-infra"))
    assert record.covered_projection("data-infra") == str(covered.ledger_path("data-infra"))
    assert record.coverage_projection("data-infra") == str(coverage.coverage_path("data-infra"))


def test_a_projected_line_carries_no_field_the_script_would_drop(seen) -> None:
    """A field the store added and the file did not would survive a projection and vanish on the
    next one the script wrote, which is the quiet way two stores of one fact come apart."""
    line = json.loads(record.seen_lines([ROW]))
    seen.record("data-infra", ROW["seen"], ROW["slug"], ROW["title"], ROW["url"], ROW["source"])
    assert line.keys() == seen.read_rows("data-infra")[0].keys()


# A complete argv for the write each script used to offer. Completeness is the whole point: the
# first version of this test passed a partial one, so a script with its `record` parser restored
# exited 2 for a *missing required argument* rather than for an unknown subcommand, and the test
# could not tell the two apart. It stayed green against a full revert — measured, after the fact.
WRITE_ARGV = {
    "seen": [
        "record", "--series", "data-infra", "--seen", "2026-09-21",
        "--slug", "acme-1-0", "--title", "Acme 1.0", "--url", "https://x/1",
    ],
    "covered": [
        "record", "--series", "data-infra", "--edition", "2026-09-28",
        "--slug", "acme-1-0", "--title", "Acme 1.0", "--url", "https://x/1",
    ],
    "coverage": [
        "record", "--series", "data-infra", "--gathered", "2026-09-28",
        "--source", "releases", "--state", "read", "--items", "3",
    ],
}


def test_no_script_writes_when_asked_to_with_a_complete_command(
    seen, covered, coverage, tmp_path
) -> None:
    """The measured reason this matters, not a style preference.

    A live fire on 2026-09-28 was told by `brief-continuity` to call `pulse_record_edition` and
    instead ran `python seen.py record --series agent-runtimes …` from its shell. Its two published
    stories went into the workspace file, which is rendered whole from the record, so both were
    pending erasure: the edition would have read as never published and the next one would have
    carried it again.

    Two assertions, because the exit code alone is not evidence. The refusal must happen on an argv
    that a restored parser would have *accepted*, and — the part that cannot be faked — no file may
    appear. A script that wrote and then exited non-zero would pass on the code alone.
    """
    for module, argv in (
        (seen, WRITE_ARGV["seen"]),
        (covered, WRITE_ARGV["covered"]),
        (coverage, WRITE_ARGV["coverage"]),
    ):
        with pytest.raises(SystemExit) as refused:
            module.main(argv)
        assert refused.value.code != 0
    assert not (tmp_path / "pulse").exists(), "a script wrote a file it has no subcommand to write"


def test_the_read_subcommands_all_still_work(seen, covered, coverage) -> None:
    """Removing the write must not have removed the reads with it."""
    assert seen.main(["history", "--series", "data-infra", "--slug", "acme-1-0"]) == 0
    assert seen.main(["fresh", "--series", "data-infra"]) == 0
    assert seen.main(["reconcile", "--series", "data-infra"]) == 0
    # `stale` is `seen.py`'s one read dispatched by fall-through rather than by an explicit branch,
    # which makes it the one a careless edit to that script's dispatch chain breaks first.
    assert seen.main(["stale", "--series", "data-infra", "--slug", "acme-1-0"]) == 1
    assert covered.main(["recent", "--series", "data-infra"]) == 0
    assert covered.main(["check", "--series", "data-infra", "--slug", "acme-1-0"]) == 0
    assert coverage.main(["window", "--series", "data-infra"]) == 0
