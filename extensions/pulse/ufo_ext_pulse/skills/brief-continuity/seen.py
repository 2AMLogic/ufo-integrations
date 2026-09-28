"""The sightings pool: what a gather has seen, separately from what an edition published.

One JSON Lines file per series at `pulse/<series>.seen.jsonl` in the conversation workspace,
append-only, one row per sighting. `record` appends a sighting; `history` reads every sighting of one
lead; `fresh` lists the leads worth pursuing now; `stale` answers whether one lead has gone quiet.

Two stores, two questions. The covered ledger answers *what has been published* and governs what an
edition may repeat. This answers *what has been seen* and governs what is worth chasing. Merging them
would lose both answers: a lead seen four times and never published is not a repeat, and a story
published once is not a lead.

Rows sharing a slug are that lead's history, exactly as they are in the covered ledger. A story seen
on Tuesday and again on Wednesday in a changed state is two rows rather than an overwrite, and the
difference between them is the evidence a material new development needs.

Nothing is ever removed. Collection is additive: a lead that goes quiet for three weeks and then
moves is still here with its whole history attached, which a pool that expired it would have
discarded at exactly the moment it became interesting. Age is a reason not to pursue a lead, never a
reason to forget it — so staleness is asked at read time, here, rather than enforced by deletion.

Staleness keys on the *most recent* sighting. A lead first seen thirty days ago and seen again this
morning is live, not old; asking how long ago it first appeared answers a different question than
whether it is still moving.

The path is workspace-relative for the same reason the covered ledger's is: only a command's argv is
rewritten to the carrier's workspace directory, never a path inside a script.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEEN_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
POOL_DIR = "pulse"
DEFAULT_WITHIN_DAYS = 14


def pool_path(series: str) -> Path:
    if not SLUG.match(series):
        raise ValueError(f"series must be a lowercase hyphenated slug, got {series!r}")
    return Path(POOL_DIR) / f"{series}.seen.jsonl"


def read_rows(series: str) -> list[dict]:
    path = pool_path(series)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def record(series: str, seen: str, slug: str, title: str, url: str, source: str) -> Path:
    if not SEEN_DATE.match(seen):
        raise ValueError(f"seen must be YYYY-MM-DD, got {seen!r}")
    if not SLUG.match(slug):
        raise ValueError(f"slug must be a lowercase hyphenated slug, got {slug!r}")
    path = pool_path(series)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"seen": seen, "slug": slug, "title": title, "url": url, "source": source}
    with path.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def history(series: str, slug: str) -> list[dict]:
    """Every sighting of one lead, oldest first — how it moved, not merely that it exists."""
    return [row for row in read_rows(series) if row["slug"] == slug]


def last_seen(series: str) -> dict[str, str]:
    """The most recent sighting date per lead. The only date staleness is allowed to ask about."""
    latest: dict[str, str] = {}
    for row in read_rows(series):
        slug, seen = row["slug"], row["seen"]
        if slug not in latest or seen > latest[slug]:
            latest[slug] = seen
    return latest


def fresh(series: str, within_days: int, today: date) -> list[tuple[str, str]]:
    """Leads whose most recent sighting is inside the window, most recently seen first."""
    cutoff = (today - timedelta(days=within_days)).isoformat()
    live = [(slug, seen) for slug, seen in last_seen(series).items() if seen >= cutoff]
    return sorted(live, key=lambda pair: pair[1], reverse=True)


def _title_of(series: str, slug: str) -> str:
    rows = history(series, slug)
    return rows[-1]["title"] if rows else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="append one sighting to the pool")
    p_record.add_argument("--series", required=True)
    p_record.add_argument("--seen", required=True)
    p_record.add_argument("--slug", required=True)
    p_record.add_argument("--title", required=True)
    p_record.add_argument("--url", default="")
    p_record.add_argument("--source", default="")

    p_history = sub.add_parser("history", help="every sighting of one lead, oldest first")
    p_history.add_argument("--series", required=True)
    p_history.add_argument("--slug", required=True)

    p_fresh = sub.add_parser("fresh", help="leads worth pursuing now")
    p_fresh.add_argument("--series", required=True)
    p_fresh.add_argument("--within-days", type=int, default=DEFAULT_WITHIN_DAYS)
    p_fresh.add_argument("--today", default=None)

    p_stale = sub.add_parser("stale", help="whether one lead has gone quiet")
    p_stale.add_argument("--series", required=True)
    p_stale.add_argument("--slug", required=True)
    p_stale.add_argument("--within-days", type=int, default=DEFAULT_WITHIN_DAYS)
    p_stale.add_argument("--today", default=None)

    args = parser.parse_args(argv)
    today = date.fromisoformat(args.today) if getattr(args, "today", None) else date.today()

    if args.command == "record":
        path = record(args.series, args.seen, args.slug, args.title, args.url, args.source)
        print(f"recorded {args.slug} seen {args.seen} ({path})")
        return 0

    if args.command == "history":
        rows = history(args.series, args.slug)
        if not rows:
            print("never seen")
            return 0
        for row in rows:
            source = f"  [{row['source']}]" if row.get("source") else ""
            print(f"{row['seen']}  {row['title']}{source}")
        return 0

    if args.command == "fresh":
        live = fresh(args.series, args.within_days, today)
        if not live:
            print("no leads seen in the window")
            return 0
        for slug, seen in live:
            print(f"{seen}  {slug:<44}{_title_of(args.series, slug)}")
        return 0

    seen = last_seen(args.series).get(args.slug)
    if seen is None:
        print("never seen")
        return 1
    cutoff = (today - timedelta(days=args.within_days)).isoformat()
    if seen < cutoff:
        print(f"last seen {seen} — stale, do not pursue without a reason")
        return 1
    print(f"last seen {seen} — live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
