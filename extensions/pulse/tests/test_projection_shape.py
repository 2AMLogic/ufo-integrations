"""The projection is the file the scripts wrote, byte for byte.

`record.py` restates three shapes the skill scripts own — the slug pattern and the two date
patterns — because a skill script is materialised standalone in a sandbox and cannot import the
extension package. Restating is not the risk; restating *and then drifting* is, because the drift
would be silent: a store that accepted a slug the script rejects writes a line the script cannot
read back, and the member's file and the agent's record would disagree about what the series holds.

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


def test_the_pool_patterns_are_the_scripts_own(seen) -> None:
    assert record.SLUG.pattern == seen.SLUG.pattern
    assert record.DATE.pattern == seen.SEEN_DATE.pattern
    assert record.POOL_DIR == seen.POOL_DIR
    assert record.DEFAULT_WITHIN_DAYS == seen.DEFAULT_WITHIN_DAYS


def test_the_ledger_patterns_are_the_scripts_own(covered) -> None:
    assert record.DATE.pattern == covered.EDITION.pattern
    assert record.POOL_DIR == covered.LEDGER_DIR
    assert record.DEFAULT_EDITIONS == covered.DEFAULT_EDITIONS


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


def test_the_projection_paths_are_the_paths_the_scripts_resolve(seen, covered) -> None:
    assert record.seen_projection("data-infra") == str(seen.pool_path("data-infra"))
    assert record.covered_projection("data-infra") == str(covered.ledger_path("data-infra"))


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
}


def test_no_script_writes_when_asked_to_with_a_complete_command(seen, covered, tmp_path) -> None:
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
    for module, argv in ((seen, WRITE_ARGV["seen"]), (covered, WRITE_ARGV["covered"])):
        with pytest.raises(SystemExit) as refused:
            module.main(argv)
        assert refused.value.code != 0
    assert not (tmp_path / "pulse").exists(), "a script wrote a file it has no subcommand to write"


def test_the_read_subcommands_all_still_work(seen, covered) -> None:
    """Removing the write must not have removed the reads with it."""
    assert seen.main(["history", "--series", "data-infra", "--slug", "acme-1-0"]) == 0
    assert seen.main(["fresh", "--series", "data-infra"]) == 0
    assert seen.main(["reconcile", "--series", "data-infra"]) == 0
    # `stale` is the one read dispatched by fall-through rather than by an explicit branch, which
    # makes it the one a careless edit to the dispatch chain breaks first.
    assert seen.main(["stale", "--series", "data-infra", "--slug", "acme-1-0"]) == 1
    assert covered.main(["recent", "--series", "data-infra"]) == 0
    assert covered.main(["check", "--series", "data-infra", "--slug", "acme-1-0"]) == 0
