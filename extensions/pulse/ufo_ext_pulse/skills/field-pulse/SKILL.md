---
name: field-pulse
description: "Load when a member asks to follow an industry, field, market, ecosystem, or research area — a recurring brief on what changed across a domain. Not for watching named competitors, which is competitive-intel, and not for one question about a field."
metadata:
  depends: [brief-continuity, coverage-honesty]
---
# Field pulse, set up in chat

A field pulse watches a domain; `competitive-intel` watches a list of companies. The difference is
what a run is allowed to find: a competitor brief reports on the names it was given, and a field
brief reports whatever moved in the field, including a name nobody had heard of last month. A member
asking to "keep up with" an area wants the second one.

The turn writes the first brief, then asks once whether it should repeat. The brief is the product and
it lands in this turn; a recurring row exists only after the member says they want one.

## Read before asking

1. The opening line states the business, and its business sentence is the enrichment's summary of the
   company — read it and never ask what the business does. `memory_search` for the field and for any
   pulse already running; finding nothing is silent, not a sentence.
   1a. When the opening line carries no business sentence at all, `memory_search` is where the business
   comes from instead — a workspace with no enrichment can still have a field recorded from an earlier
   turn. Only when that search also comes back empty is the business genuinely unknown, and that is the
   one case worth a question: in one message, ask which business or field to track, in the same short
   numbered-list style as "Ask only what blocks the brief" below. This is not the asking step 1 rules
   out — it is what is left once both sources have been tried and neither answered.
2. Name the field back in one sentence before proposing anything. "Open-source data infrastructure"
   and "the data industry" produce different briefs, and the narrower one is almost always what they
   meant. A field too broad to bound is the one thing worth asking about.
3. Propose the source kinds, do not request them. One web search on the field names its venues:
   where releases land, where its research is posted, where its practitioners argue, which registries
   or indexes record its activity. Ask the member to confirm, drop, or add. "What sources do you
   want?" is the trap — the member came to be told where to look.

## Ask only what blocks the brief

One message, one short numbered list: confirm the field sentence, and confirm the proposed sources as
a yes/no. Cadence is not asked here. "Set it up" and "go ahead" are confirmation of the brief; do not
ask again.

## Write the first brief

Load `research-assistant` and find what changed across the confirmed sources, bounding every query to
the recent past. Set each source's state as its read returns, per `coverage-honesty`'s three states,
and record it under this gather's date with `brief-continuity`'s `coverage.py` — an edition covering
more than one gather writes its footer from those rows, and the row is only writable while the read
is in front of you.

`brief-continuity` and `coverage-honesty` arrive with this skill and hold the two contracts a series
lives by: what an edition may repeat, and what it may claim about a source it could not read. They are
loaded, not optional.

Record every candidate in the sightings pool before ranking, with `brief-continuity`'s `seen.py` —
everything the gather surfaced, not only what is about to be published. A sighting is a fact at the
moment the source returned it; whether it clears the bar is a separate judgement made after, and
recording the two at the same moment is how a pool ends up holding only what an edition already
carried.

The business-relative bar below makes this more valuable rather than less. It rejects more than a
field-relative one did, and every rejection is a lead rather than nothing: a story that changes
nothing for this business today is exactly the one that may change something next month, and the
pool is what lets a later edition tell it apart from a lead that has gone quiet for good.

Rank what you found, against the business rather than the field. Importance is whether this changes
a decision, a plan, a cost, a risk or a dependency for *this* business — not whether someone working
in the field would find it notable. The business sentence that chose the field is the same sentence
that ranks inside it; a brief that stops using it after step 1 is a brief about an industry, and the
reader did not ask for one. Source signals inform the ranking and do not decide it. Cluster the
sources covering one story and rank the story once, on its own weight rather than the sum of its
coverage.

Five to ten stories carry an edition, but that is a ceiling rather than a quota. The count is a
consequence of the bar: publish what clears it and stop. Reaching for a number is how a brief about
this business becomes a brief about its field, and the reader stops at the point where ranking
stopped being visible.

An edition where nothing clears the bar is a finished edition, not a failed one. Say plainly that
the window was quiet and name what was read, and never lower the bar to fill a page — a reader who
is told "nothing this week" and can believe it is the reader this brief is for. That claim is only
worth anything with `coverage-honesty`'s footer under it: a quiet window is every source read and
nothing clearing the bar, and an edition reporting quiet on top of sources it could not read is the
failure that skill exists to prevent, not a quiet day.

Each story gets a headline in the reader's plain language — not the source's headline — and two to
four sentences on why it matters. Say what a thing claims, not what it might mean, and say plainly
when something is early, small, or unproven. No superlatives, and no word the reader would not use
about their own work.

Load `research-report` and write `<series>-<date>.md`. Close the brief with the footer
`coverage-honesty` specifies. Reply with the brief itself, never with a promise of one.

This is the first edition, so there is no ledger to read. Record the edition's stories with
`brief-continuity` once the brief is written — every later fire depends on this edition having
recorded what it covered.

**If a write fails, say so in the reply.** Recording the edition, writing the report file and
appending to the pool and the coverage store all need a workspace a command can write to, and not
every run has one: a fire with no client attached has no file tools at all. Such a run still
gathers, ranks and replies perfectly well, so the edition looks finished while the ledger learned
nothing — and the next edition, reading a ledger missing this one, repeats it. A series quietly
stops being a series.

So a failed write is part of the brief, not a detail to swallow: name what could not be written and
that continuity is broken for this edition. An edition that could not record itself is worth less
than one that says it could not. This is the same rule `coverage-honesty` applies to a source that
did not answer, pointed at the series' own record instead of its inputs.

## Ask once whether it repeats

After the brief, and only after it, ask once with `ask_user`: keep this as a one-time brief, or run it
on a schedule. Recommend **two or three times a week**, not daily. A field produces news on its own
clock and a daily fire lands on empty windows, which trains the reader to skip the brief; two or three
editions a week is the cadence where every edition has something in it. A member who names a cadence
has answered — apply it and ask nothing.

## Apply the task, once they asked for a recurring one

A one-time answer ends here: say the brief is written, name the file, offer nothing else.

For a recurring answer, load `task-scheduling` and apply one manifest named `<field>-pulse`. Fire in
the member's morning, read from the `<context>` header's `time:` line and converted to UTC. Carry no
`run_now`: the first edition was written in this turn, and an immediate fire would research the same
window twice and publish it twice.

```yaml
kind: scheduled_task
name: <field>-pulse
spec:
  schedule: "0 13 * * 1,3,5"
  description: <Field> pulse, Monday/Wednesday/Friday
  prompt: |
    Write the <field> pulse for <business>. Rank against that business, not the field: a story
    earns a slot by changing a decision, a plan, a cost, a risk or a dependency for it, and five
    to ten is a ceiling rather than a quota — publish what clears the bar and stop. Load
    brief-continuity and read the covered ledger for series <series> before ranking anything — a
    story the last five editions published is ineligible without a material new development. Load
    research-assistant and find what changed across <the confirmed sources> since the previous
    edition, and record every candidate it surfaces in the sightings pool with brief-continuity's
    seen.py before ranking — everything seen, not only what you publish. Load coverage-honesty and
    set each source's state as it returns, recording each one under this gather's date with
    brief-continuity's coverage.py; name every unread source in the footer, and where the edition
    covers more than one gather say how many of them it went unread on. Load research-report and
    write <series>-<date>.md. Record the published stories with brief-continuity. If any write
    fails — the report file, the ledger, the pool or the coverage store — say so in the reply and
    say that continuity is broken for this edition; a fire with no client attached has no file
    tools, and an edition that silently recorded nothing is repeated by the next one. Reply with
    the brief; when nothing clears the bar, say the window was quiet and never lower the bar to
    fill it.
```

Every field is filled from this member's own answers. A source carried over from this example is a
source nobody confirmed.

`task-scheduling` bounds tasks that fire daily or more often with an `expires_at`. A two- or
three-a-week pulse is not one of those, so it carries no expiry.

## Record what lasts

Before applying, `memory_update` one item for the field sentence and one for the confirmed source
set. Per-edition findings are the reply and the report file, never a memory item — the covered ledger
is a workspace file for the same reason.

## Close

Four lines at most: what it watches, that the first edition is the one above, when it fires from now
on, and that every edition lands in this conversation.

## Traps

- Running this for a list of named companies, which is `competitive-intel`.
- Asking which sources to watch instead of proposing them.
- Accepting a field too broad to bound, which produces a brief about everything.
- Asking about cadence before the member has read an edition.
- Defaulting to daily, so most editions land on an empty window.
- Carrying `run_now: true`, which publishes this turn's window twice.
- Skipping the ledger record on the first edition, which leaves the second one no baseline.
- Letting the schedule's prompt name the sources while the ledger series name is left as a placeholder.
- Writing a headline in the source's words rather than the reader's.
- Recording only what you publish, which leaves the pool blind to every lead the bar rejected.
- Leaving a gather's source states unrecorded, so an edition spanning several of them can report
  only the last one's failures.
- Replying with a finished-looking edition after a write failed, which leaves the next edition to
  repeat it.
- Padding a thin window to reach a story count, which turns a brief about this business back into a
  brief about its field.
- Calling a window quiet over sources that went unread, which is the one claim `coverage-honesty`
  exists to refuse.
- Deriving a field, or proceeding silently, when neither the opening line nor `memory_search` has
  supplied a business — the turn has nothing to ask a field or rank stories against, and step 1a's
  question is the only correct move.
- Assuming an edit to this skill reaches an armed row. `task-scheduling`'s manifest stores its
  `prompt` on the scheduled row at apply time, and a fire runs that stored copy, not this file — an
  armed pulse keeps the rule it was set up under until someone re-applies the manifest. Re-applying
  `<field>-pulse` upserts it in place and re-points reporting to whichever conversation ran the
  re-apply, so a member who wants the new rule re-applies from the pulse's own conversation, not from
  wherever the skill was edited. Same family as #70's running `serve` process keeping the skills it
  booted with — a durable copy an edit does not reach, different surface.
