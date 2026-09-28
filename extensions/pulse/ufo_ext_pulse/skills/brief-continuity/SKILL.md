---
name: brief-continuity
description: "Load when a recurring brief, digest, or watch must not repeat what an earlier edition of the same series already published, when a member says a report keeps telling them what they already know, or to track leads already seen. Not for a first brief with no prior edition."
---
# Brief continuity

A recurring brief is a series. Its reader has read the last one, so the question this edition answers
is not "what is true about this field" but "what changed since the edition before it." Those two
questions select different stories, and a run that answers the first one publishes last week's brief
again with today's date on it.

The covered ledger is what makes the difference decidable. It is a workspace file —
`pulse/<series>.covered.jsonl` — one row per story the series has published, written by the run that
published it and read by the run after. The workspace is where it belongs twice over: the member can
open it there, and it is the one tree every carrier lets a command write. Never in memory:
`task-scheduling` puts an already-covered ledger in workspace files because a per-run snapshot
written as a memory fact is injected into unrelated later turns.

## Read the ledger before ranking, not after

Read it first. A story's eligibility decides whether it is worth researching further, so a run that
ranks and then filters spends the whole window's effort on stories it then throws away.

```bash
python "$UFO_HOME/skills/brief-continuity/covered.py" recent --series <series> --editions 5
```

Run it from the workspace root, which is where a command starts: the ledger path is relative, so a
run that changes directory first reads an empty ledger and carries the last edition again.

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

## The sightings pool is a second store, not a second ledger

`pulse/<series>.seen.jsonl`, written by `seen.py`, records what a gather has **seen**. The covered
ledger records what an edition **published**. They answer different questions and must not be
merged: a lead seen four times and never published is not a repeat, and a story published once is
not a lead.

```bash
python "$UFO_HOME/skills/brief-continuity/seen.py" record --series <s> --seen <date> --slug <slug> --title <t>
python "$UFO_HOME/skills/brief-continuity/seen.py" fresh   --series <s> --within-days 14
python "$UFO_HOME/skills/brief-continuity/seen.py" stale   --series <s> --slug <slug>
python "$UFO_HOME/skills/brief-continuity/seen.py" history --series <s> --slug <slug>
```

Fourteen days is the window both `fresh` and `stale` default to, and it is the same kind of number
as the five-edition span above: two weeks is roughly how long a lead stays worth chasing before its
silence is the story. Pass `--within-days` where a field moves faster or slower.

The pool is append-only and nothing is ever removed. Age is a reason not to pursue a lead, never a
reason to forget it: `stale` exits non-zero for a lead that has gone quiet, and the lead stays in
the pool with its whole history, so when it moves again that history is still attached. A pool that
expired it would have discarded it at exactly the moment it became interesting.

**Staleness keys on the most recent sighting, not the first.** A lead first seen thirty days ago and
seen again this morning is live. Asking when it first appeared answers a different question.

Rows sharing a slug are that lead's history, exactly as they are in the ledger. Two sightings of one
story in different states are two rows rather than an overwrite, and the difference between them is
the evidence the material-new-development exception wants — better evidence than the ledger alone
gives, because it records how a story moved between editions rather than only that an edition
carried it.

Every read is a pure read. `stale`, `fresh` and `history` never write, mark or delete a row; a
staleness check that wrote anything would be the expiry this design rules out, wearing a different
name.

`record` is deliberately not idempotent. A sighting is an observation, not a fact about a story, so
seeing one story twice in a day is two observations and both are recorded. `fresh` and `stale` read
the most recent sighting and are unaffected; `history` is where the repetition shows, which is the
place it is worth seeing — a lead a source keeps re-running is behaving differently from one that
appeared once.

## Coverage state is a third store, one row per source per gather

`pulse/<series>.coverage.jsonl`, written by `coverage.py`, records what each source returned on each
gather: read with items, read and empty, or not read for one of `coverage-honesty`'s four reasons.
The ledger's subject is a story and the pool's is a lead; this one's is a source, which is why it
carries no slug for a story and answers what neither of the others can.

```bash
python "$UFO_HOME/skills/brief-continuity/coverage.py" record \
  --series <s> --gathered <date> --source <source-slug> --state read --items 11
python "$UFO_HOME/skills/brief-continuity/coverage.py" record \
  --series <s> --gathered <date> --source <source-slug> --state not-read --reason rate-limited
python "$UFO_HOME/skills/brief-continuity/coverage.py" window \
  --series <s> --since <date> --until <date>
```

`window` states every source across the gathers between those dates: read on all three, not read on
two of three, not read throughout. An edition covering one gather has one set of states to report and
an edition covering three has three, and `coverage-honesty` is what the footer follows in either case.

The source slug is that source's durable address across gathers, exactly as a story slug is across
editions. The footer names the source in the reader's words and the store keys it by the slug, which
is what lets three days of one source aggregate as one source rather than as three.

A retry inside one gather appends its own row, and the later row is that gather's answer: a source
that rate-limited the first attempt and answered the second was read that day. Nothing is rewritten,
and every read here is a pure read, exactly as in the pool.

## Traps

- Ranking before reading the ledger, then discarding the winners.
- Treating the gathering window as the baseline, so a story fetched twice publishes twice.
- Letting fresh engagement reopen a covered story with nothing new under it.
- Recapping the original before the new fact, under the exception.
- Giving a carried story a new slug, which hides that the series has covered it before.
- Writing rows while drafting, so a cut story is recorded as published.
- Running the script from a subdirectory, which starts a second ledger the next edition cannot find.
- Saving the ledger as a memory fact, which pushes single-run snapshots into unrelated turns.
- Reading more than five editions back and calling a genuinely old story ineligible forever.
- Recording a sighting in the covered ledger, which marks an unpublished lead as already covered.
- Deleting or rewriting a pool row to express staleness, rather than letting `stale` answer it.
- Keying a source by the words one footer used, so one source across three gathers aggregates as three.
- Rewriting a gather's coverage row when a retry succeeds, instead of appending the retry beside it.
