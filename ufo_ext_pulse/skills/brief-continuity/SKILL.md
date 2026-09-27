---
name: brief-continuity
description: "Load when a recurring brief, digest, or watch must not repeat what an earlier edition of the same series already published, or when a member says a report keeps telling them what they already know. Not for a first brief with no prior edition."
---
# Brief continuity

A recurring brief is a series. Its reader has read the last one, so the question this edition answers
is not "what is true about this field" but "what changed since the edition before it." Those two
questions select different stories, and a run that answers the first one publishes last week's brief
again with today's date on it.

The covered ledger is what makes the difference decidable. It is a workspace file, one row per story
the series has published, written by the run that published it and read by the run after. Keep it in
the workspace, never in memory: `task-scheduling` puts an already-covered ledger in workspace files
because a per-run snapshot written as a memory fact is injected into unrelated later turns.

## Read the ledger before ranking, not after

Read it first. A story's eligibility decides whether it is worth researching further, so a run that
ranks and then filters spends the whole window's effort on stories it then throws away.

```bash
python "$UFO_HOME/skills/brief-continuity/covered.py" recent --series <series> --editions 5
```

The last five editions are the baseline. Older coverage has left the reader's head and may be
carried again as new; five editions is the span a returning reader holds.

## Covered means ineligible

A story any of the last five editions published is ineligible for this one. It is ineligible as a
headline, as a one-line mention, and as a footnote, and it stays ineligible when it resurfaces with
more engagement than it had the first time. Engagement measures how many people are still reading it,
which is not the same claim as something having happened.

Re-surfacing is the normal case, not the exception. A multi-day window overlaps the previous window's
tail, discussion of a launch peaks days after the launch, and an aggregator's ranking lifts a story
twice. The published series is the baseline for this decision — never the gathering window, which
only says what was fetched.

## The one exception is a material new development

A covered story becomes eligible again when something happened to it that a reader of the earlier
edition does not know. Four things qualify:

| Development | Not a development |
| --- | --- |
| A release shipped that was announced before | More coverage of the announcement |
| A deal, raise, or acquisition closed | A rumor restated by a second outlet |
| A number was confirmed, or corrected | A number quoted again |
| A reversal, withdrawal, or shutdown | Commentary on the original |

Then lead with what is new. The earlier edition carries the background, so an entry that opens by
recapping the original is spending the reader's first line on what they read last week.

    Bad:   Acme's open compiler, announced in March as a rewrite of its
           toolchain, has now shipped its first release
    Good:  Acme's compiler rewrite shipped, six weeks after the March announcement

One clause of background is the budget, and it goes after the new fact, not before it.

## Write the ledger when the edition publishes

Every story that reaches the published edition gets a row, and the rows are written once the edition
is out — not while drafting, or a story cut in the last pass reads as covered to the next run and is
never carried at all.

```bash
python "$UFO_HOME/skills/brief-continuity/covered.py" record \
  --series <series> --edition <YYYY-MM-DD> --slug <story-slug> --title <title> --url <url>
```

The slug is the story's durable address across editions, so it names the thing that happened and not
the way this edition phrased it: `acme-compiler-1-0-shipped`, never `big-week-for-acme`. A story
carried again under the material-new-development exception keeps its original slug — that is what
makes the second entry findable as a second entry.

A cluster of sources covering one story is one row. The row carries the primary link; the edition
carries the rest.

## Traps

- Ranking before reading the ledger, then discarding the winners.
- Treating the gathering window as the baseline, so a story fetched twice publishes twice.
- Letting fresh engagement reopen a covered story with nothing new under it.
- Recapping the original before the new fact, under the exception.
- Giving a carried story a new slug, which hides that the series has covered it before.
- Writing rows while drafting, so a cut story is recorded as published.
- Saving the ledger as a memory fact, which pushes single-run snapshots into unrelated turns.
- Reading more than five editions back and calling a genuinely old story ineligible forever.
