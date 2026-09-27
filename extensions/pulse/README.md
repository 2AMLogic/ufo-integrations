# ufo-ext-pulse

A recurring field brief for [ufo](https://github.com/ufo-ai/ufo-core): three skills that make a
series of briefs behave like a series.

`competitive-intel` watches a list of companies. A field pulse watches a domain, so a run may find a
name nobody had heard of last month. That difference is why this is a separate skill, but it is not
the reason this extension exists.

## What it adds

A recurring brief has two failure modes that a single well-written report does not have, and neither
is fixed by writing the report better.

**It repeats itself.** The reader has read the last edition, so this one has to answer "what changed
since then" rather than "what is true about this field." `task-scheduling` tells a run to keep an
already-covered ledger in workspace files; nothing defines one. `brief-continuity` does: an
append-only ledger, read before ranking, where a story published in the last five editions is
ineligible unless something happened to it that the earlier reader does not know — a release shipped,
a deal closed, a number confirmed or corrected, a reversal. `covered.py` makes that a lookup instead
of a recollection.

**It reports silence it did not observe.** A source that rate-limited the run and a source with
nothing in it both return zero items, and a brief that renders the first as the second tells the
reader the field is quiet on the strength of having looked at nothing. `coverage-honesty` gives every
source three states rather than two, names each unread source in the footer, and refuses to publish
an edition at all when most sources went unread — because a brief built from the half that answered
looks like a normal edition, so nobody goes back for the other half.

`field-pulse` sets a pulse up in chat, writes the first edition in that turn, and schedules the rest.
It carries the other two as `metadata.depends`, so a pulse run cannot load the workflow without the
contracts.

| Skill | Holds |
| --- | --- |
| `field-pulse` | Setting one up, writing an edition, the recurring row |
| `brief-continuity` | The covered ledger; what an edition may repeat |
| `coverage-honesty` | What a run may claim about a source it could not read |

The extension declares three skills and nothing else — no tool, no schedule kind, no store.
Gathering is `research`'s, the recurring row is `scheduled_tasks`', the feed entry is
`report_digest`'s, and the ledger is a workspace file the member can read.

## Install

```bash
pip install ufo-ext-pulse
ufoctl ext install pulse
```

The `ufo.extension` entry point registers the pack; the next `ufoctl serve` loads it. A deploy with
pulse active and no search backend fails at boot, which is what `requires = ("search_providers",)`
is for.

## The ledger

One JSON Lines file per series under `$UFO_HOME/pulse/<series>.covered.jsonl`, one row per story per
edition, append-only.

```bash
python "$UFO_HOME/skills/brief-continuity/covered.py" recent --series data-infra --editions 5
python "$UFO_HOME/skills/brief-continuity/covered.py" check --series data-infra --slug acme-1-0
```

`check` exits non-zero when the slug is covered in the span. A story carried again under the
material-new-development exception keeps its original slug, so the rows sharing a slug are that
story's history across the series.

## Tests

```bash
pytest tests/
```

## License

Apache-2.0.
