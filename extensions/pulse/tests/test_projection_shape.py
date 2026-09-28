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
