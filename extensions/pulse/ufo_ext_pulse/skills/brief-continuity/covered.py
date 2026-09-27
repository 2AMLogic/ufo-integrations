"""The covered ledger: what a brief series has already published, and what it may carry again.

One JSON Lines file per series under `$UFO_HOME/pulse/<series>.covered.jsonl`, append-only, one row
per story per edition. `record` appends a row; `recent` reads the rows belonging to the last N
editions; `check` answers whether one slug is inside that span. A slug carried again under the
material-new-development exception appears once per edition that carried it, so the history of a
story is the rows sharing its slug.

Append-only is what makes the ledger readable as history: a row states that an edition published a
story, which stays true after the story develops.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EDITION = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_EDITIONS = 5


def ledger_path(series: str) -> Path:
    if not SLUG.match(series):
        raise ValueError(f"series must be a lowercase hyphenated slug, got {series!r}")
    home = Path(os.environ.get("UFO_HOME", Path.home() / ".ufo"))
    return home / "pulse" / f"{series}.covered.jsonl"


def read_rows(series: str) -> list[dict]:
    path = ledger_path(series)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def recent_rows(series: str, editions: int) -> list[dict]:
    """Every row belonging to the most recent `editions` distinct edition dates.

    The span is counted in editions rather than days because a series sets its own cadence: five
    editions is five briefs the reader has seen, whether they fell over one week or three.
    """
    rows = read_rows(series)
    dates = sorted({row["edition"] for row in rows}, reverse=True)[:editions]
    return [row for row in rows if row["edition"] in set(dates)]


def record(series: str, edition: str, slug: str, title: str, url: str) -> Path:
    if not EDITION.match(edition):
        raise ValueError(f"edition must be YYYY-MM-DD, got {edition!r}")
    if not SLUG.match(slug):
        raise ValueError(f"slug must be a lowercase hyphenated slug, got {slug!r}")
    path = ledger_path(series)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"edition": edition, "slug": slug, "title": title, "url": url}
    with path.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="append one published story to the ledger")
    p_record.add_argument("--series", required=True)
    p_record.add_argument("--edition", required=True)
    p_record.add_argument("--slug", required=True)
    p_record.add_argument("--title", required=True)
    p_record.add_argument("--url", default="")

    p_recent = sub.add_parser("recent", help="rows from the last N editions")
    p_recent.add_argument("--series", required=True)
    p_recent.add_argument("--editions", type=int, default=DEFAULT_EDITIONS)

    p_check = sub.add_parser("check", help="whether a slug is covered in the last N editions")
    p_check.add_argument("--series", required=True)
    p_check.add_argument("--slug", required=True)
    p_check.add_argument("--editions", type=int, default=DEFAULT_EDITIONS)

    args = parser.parse_args(argv)

    if args.command == "record":
        path = record(args.series, args.edition, args.slug, args.title, args.url)
        print(f"recorded {args.slug} in {args.edition} ({path})")
        return 0

    if args.command == "recent":
        rows = recent_rows(args.series, args.editions)
        if not rows:
            print("no editions recorded")
            return 0
        for row in rows:
            print(f"{row['edition']}  {row['slug']:<40}{row['title']}")
        return 0

    rows = recent_rows(args.series, args.editions)
    hits = [row for row in rows if row["slug"] == args.slug]
    if hits:
        editions = ", ".join(sorted({row["edition"] for row in hits}))
        print(f"covered in {editions} — ineligible without a material new development")
        return 1
    print("not covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
