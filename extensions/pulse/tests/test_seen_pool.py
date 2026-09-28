"""The sightings pool, run against a temporary workspace.

The pool's whole value is that it is additive: these assert that reading it — including asking
whether a lead is stale — never changes it, because the moment staleness writes anything it has
become the expiry the design rules out.
"""

from datetime import date
from pathlib import Path

import pytest


def test_an_unseen_series_reads_empty(seen) -> None:
    assert seen.read_rows("data-infra") == []
    assert seen.main(["history", "--series", "data-infra", "--slug", "acme-1-0"]) == 0


def test_a_series_name_cannot_escape_its_directory(seen) -> None:
    with pytest.raises(ValueError):
        seen.pool_path("../escape")


def test_the_pool_lands_in_the_workspace_beside_the_ledger(seen, tmp_path, monkeypatch) -> None:
    """Workspace-relative for the same reason the covered ledger is, and a `UFO_HOME` elsewhere
    moves nothing."""
    monkeypatch.setenv("UFO_HOME", str(tmp_path / "scratch" / "ufo"))
    path = seen.record("data-infra", "2026-09-21", "acme-1-0", "Acme 1.0", "https://x/1", "releases")
    assert path == Path("pulse/data-infra.seen.jsonl")
    assert (tmp_path / "pulse" / "data-infra.seen.jsonl").is_file()


def test_two_sightings_of_one_lead_are_two_rows(seen) -> None:
    """Not an overwrite: the difference between the rows is what evidences a development."""
    seen.record("data-infra", "2026-09-21", "acme-1-0", "Acme 1.0 in beta", "https://x/r", "releases")
    seen.record("data-infra", "2026-09-23", "acme-1-0", "Acme 1.0 GA", "https://x/r", "releases")
    rows = seen.history("data-infra", "acme-1-0")
    assert [row["seen"] for row in rows] == ["2026-09-21", "2026-09-23"]
    assert rows[0]["title"] != rows[1]["title"]


def test_staleness_keys_on_the_most_recent_sighting(seen) -> None:
    """A lead first seen long ago but seen again this morning is live, not old."""
    seen.record("data-infra", "2026-08-01", "acme-1-0", "Acme 1.0 rumoured", "https://x/f", "forums")
    seen.record("data-infra", "2026-09-27", "acme-1-0", "Acme 1.0 GA", "https://x/r", "releases")
    assert (
        seen.main(
            ["stale", "--series", "data-infra", "--slug", "acme-1-0", "--today", "2026-09-28"]
        )
        == 0
    )


def test_a_lead_that_went_quiet_is_stale(seen) -> None:
    seen.record("data-infra", "2026-08-01", "old-news", "Something from August", "https://x/f", "forums")
    assert (
        seen.main(["stale", "--series", "data-infra", "--slug", "old-news", "--today", "2026-09-28"])
        == 1
    )


def test_a_never_seen_lead_is_not_live(seen) -> None:
    assert (
        seen.main(["stale", "--series", "data-infra", "--slug", "nothing", "--today", "2026-09-28"])
        == 1
    )


def test_a_stale_lead_is_still_in_the_pool_with_its_history(seen) -> None:
    """The point of additive collection: going quiet loses a lead no data at all, so when it moves
    again its whole history is still attached."""
    seen.record("data-infra", "2026-08-01", "old-news", "Something from August", "https://x/f", "forums")
    seen.main(["stale", "--series", "data-infra", "--slug", "old-news", "--today", "2026-09-28"])
    assert len(seen.history("data-infra", "old-news")) == 1

    seen.record("data-infra", "2026-09-28", "old-news", "It moved after all", "https://x/r", "releases")
    assert len(seen.history("data-infra", "old-news")) == 2
    assert (
        seen.main(["stale", "--series", "data-infra", "--slug", "old-news", "--today", "2026-09-28"])
        == 0
    )


def test_reading_never_writes(seen, tmp_path) -> None:
    """The constraint that keeps this a pool rather than an expiry: no read path — stale, fresh or
    history — may write, mark or delete a row. Asserted on the file's bytes, so any future write
    dressed up as a read fails here."""
    seen.record("data-infra", "2026-08-01", "old-news", "Something from August", "https://x/f", "forums")
    seen.record("data-infra", "2026-09-27", "live-news", "Something recent", "https://x/r", "releases")
    path = tmp_path / "pulse" / "data-infra.seen.jsonl"
    before = path.read_bytes()

    seen.main(["fresh", "--series", "data-infra", "--today", "2026-09-28"])
    seen.main(["stale", "--series", "data-infra", "--slug", "old-news", "--today", "2026-09-28"])
    seen.main(["stale", "--series", "data-infra", "--slug", "live-news", "--today", "2026-09-28"])
    seen.main(["history", "--series", "data-infra", "--slug", "old-news"])
    seen.last_seen("data-infra")
    seen.fresh("data-infra", 14, date(2026, 9, 28))

    assert path.read_bytes() == before


def test_fresh_lists_only_leads_inside_the_window(seen) -> None:
    seen.record("data-infra", "2026-08-01", "old-news", "August", "https://x/f", "forums")
    seen.record("data-infra", "2026-09-27", "live-news", "Recent", "https://x/r", "releases")
    live = seen.fresh("data-infra", 14, date(2026, 9, 28))
    assert [slug for slug, _ in live] == ["live-news"]


def test_the_pool_is_a_different_file_from_the_ledger(seen, covered, tmp_path) -> None:
    """Two stores, two questions. A lead seen four times and never published is not a repeat, and
    the covered ledger must not learn about it."""
    seen.record("data-infra", "2026-09-27", "acme-1-0", "Acme 1.0", "https://x/r", "releases")
    assert (tmp_path / "pulse" / "data-infra.seen.jsonl").is_file()
    assert not (tmp_path / "pulse" / "data-infra.covered.jsonl").exists()
    assert covered.main(["check", "--series", "data-infra", "--slug", "acme-1-0"]) == 0


def test_fresh_separates_a_max_length_slug_from_its_title(seen, capsys) -> None:
    """A slug exactly as wide as the column pad left no gap at all, which only shows with a real
    slug — every fixture here was short enough to hide it."""
    wide = "kicad-ai-assistant-plugin-gemini-fix-release"  # 44 chars, the pad width
    seen.record("data-infra", "2026-09-27", wide, "A title that must not abut", "https://x/g", "github")
    seen.main(["fresh", "--series", "data-infra", "--today", "2026-09-28"])
    line = capsys.readouterr().out.strip()
    assert f"{wide}  " in line, line


def test_a_sighting_without_a_url_is_refused(seen) -> None:
    """The url is the only thing outside a run that two sightings of one story agree on, so a row
    without one can never be reconciled with another. Losing it silently is unrepairable later."""
    with pytest.raises(ValueError, match="url is required"):
        seen.record("data-infra", "2026-09-27", "no-url", "No url", "", "releases")


def test_a_whitespace_only_url_is_refused_too(seen) -> None:
    """A blank url at least announces itself; " " looks like a value and reconciles no better."""
    with pytest.raises(ValueError, match="url is required"):
        seen.record("data-infra", "2026-09-27", "blank-url", "Blank", "   ", "releases")
