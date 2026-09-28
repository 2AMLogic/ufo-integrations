# ufo-ext-pulse

A recurring field brief for [ufo](https://github.com/ufo-ai/ufo-core): four skills that make a
series of briefs behave like a series.

`competitive-intel` watches a list of companies. A field pulse watches a domain, so a run may find a
name nobody had heard of last month. That difference is why this is a separate skill, but it is not
the reason this extension exists.

## What it adds

A recurring brief has three failure modes that a single well-written report does not have, and none
of them is fixed by writing the report better.

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

**It pays for research it publishes and publishes research nobody asked for.** A field moves every
day, so research is worth doing every day; an edition is worth reading when the member decides to
read one, which no schedule knows. A single fire that gathers and publishes has to pick one clock for
both, and either answer is wrong: at a reader's cadence it searches on two days in seven, and at the
field's cadence it delivers seven editions a week to someone who wanted two. So the recurring row
gathers and records, and `field-report` writes an edition when it is asked for — from the pool, with
no search in the request path, which is also what makes it fast enough to answer in the conversation.

`field-pulse` sets a pulse up in chat, writes the first edition in that turn, and arms the daily
gather. It carries the other three as `metadata.depends`, so a pulse run cannot load the workflow
without the writer or the contracts.

| Skill | Holds |
| --- | --- |
| `field-pulse` | Setting one up, the first edition, the daily gather |
| `field-report` | An edition on demand, from the pool, with no fresh search |
| `brief-continuity` | The covered ledger and the sightings pool; what an edition may repeat |
| `coverage-honesty` | What a run may claim about a source it could not read |

The extension declares four skills and nothing else — no tool, no schedule kind, no store.
Gathering is `research`'s, the recurring row is `scheduled_tasks`', the feed entry is
`report_digest`'s, and the ledger and the pool are workspace files the member can read.

## Install

```bash
pip install "ufo-integrations @ git+https://github.com/2AMLogic/ufo-integrations"
```

Installing the distribution registers the `ufo.extension` entry point. What activates pulse is the
deploy's active extension set, and `ufoctl init` writes `[pack] name = "assistant"` into `ufo.toml`:
a named pack narrows that set to exactly the extensions it bundles, and the assistant pack bundles
neither `pulse` nor the `research` extension a pulse gathers through. Under it the install is
inactive, and nothing says so.

The way through is a pack of this deploy's own, bundling the assistant set plus both, named in
`ufo.toml` in place of `assistant`. Two files under `packs/deploy/`:

```toml
# packs/deploy/pyproject.toml
[project]
name = "ufo-pack-deploy"
version = "0.1.0"
requires-python = ">=3.12"

[project.entry-points."ufo.pack"]
deploy = "ufo_pack_deploy:pack"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

```python
# packs/deploy/ufo_pack_deploy.py
"""The extensions this deploy brings up together: ufo-core's assistant set, plus pulse and the
research extension a pulse gathers through."""

from ufo.sdk.manifest import Pack
from ufo_pack_assistant import EXTENSIONS as ASSISTANT

NAME = "deploy"
VERSION = "0.1.0"
EXTENSIONS = (*ASSISTANT, "research", "pulse")


def pack() -> Pack:
    return Pack(name=NAME, version=VERSION, extensions=EXTENSIONS)
```

Reading `EXTENSIONS` from the pack ufo-core ships, rather than copying the names it holds, keeps the
set tracking upstream's. Then `pip install ./packs/deploy`, set `[pack] name = "deploy"`, and the
next `ufoctl serve` comes up with pulse active.

## Keys

Each resolves `UFO_<NAME>` from the environment first and the bare `<NAME>` second, so all three
belong in the `.env` beside `ufo.toml` under their `UFO_`-prefixed names — a bare
`ANTHROPIC_API_KEY` or `OPENAI_API_KEY` there is refused by name, because every tool reading `.env`
picks those up. `ufoctl init` echoes one informational line per unset key an active extension
declares as a deploy key, `UFO_OPENAI_API_KEY` among them, and proceeds either way. The model
provider's key and the search slot are not deploy keys, so a deploy reaches `ufoctl serve` with all
three unset and a line about one.

| Key | Holds | Unset |
| --- | --- | --- |
| `UFO_ANTHROPIC_API_KEY` | A model provider's key; `UFO_OPENAI_API_KEY` serves in its place | With neither resolving, `ufoctl serve` refuses to boot: `no model provider key set; the sandbox would have no egress route` |
| `UFO_OPENAI_API_KEY` | Embeddings, whichever provider serves the model | Index derivation raises on every turn, so recall finds nothing |
| `perplexity_api_key` | The search backend, as a workspace credential slot filled in chat, or a deploy-wide `UFO_PERPLEXITY_API_KEY` under it | The deploy boots, and the first gather raises `CredentialSlotUnset` inside the job |

A missing backend and an unfilled slot fail in different places, and the first of the two is what
`requires = ("search_providers",)` is for: boot refuses when `[research] search_provider` is unset,
when no active extension registers the backend it names, or when the credential store itself is
unkeyed — never because a declared slot is empty. The slot is read per request, so an unfilled one
boots clean and fails loud in the turn.

The embed backend is OpenAI's whichever provider serves the model, and it reads its key per embed
call rather than at boot, so a deploy configured entirely with Anthropic boots clean and then raises
inside the indexing job on every turn. A pulse turn opens on `memory_search` for the field and for
any pulse already running; with nothing in the index that search finds nothing, which is also what a
field nobody has asked about looks like. The constraint is upstream's, on any deploy with memory
active, rather than this extension's.

## The two stores

One JSON Lines file per series per store, in the conversation workspace, append-only:
`pulse/<series>.covered.jsonl` holds one row per story per edition, and `pulse/<series>.seen.jsonl`
holds one row per sighting a gather recorded. They answer different questions — what the series has
published, and what it has seen — and a lead seen four times and never published is not a repeat.
An edition reads both: the ledger decides what it may carry, the pool is everything it has to carry.

Both paths are workspace-relative and resolve against the working directory a sandbox command starts
in, so the files land where the member can open them and where a carrier that runs commands can
write. A turn reaching the surface without one writes neither — see Traps.

```bash
python "$UFO_HOME/skills/brief-continuity/covered.py" check --series data-infra --slug acme-1-0
python "$UFO_HOME/skills/brief-continuity/seen.py" fresh --series data-infra --within-days 14
```

`check` exits non-zero when the slug is covered in the span, and `fresh` lists the leads whose most
recent sighting is inside the window. A story carried again under the material-new-development
exception keeps its original slug, so the rows sharing a slug are that story's history across the
series in either store.

## Traps

- **The deploy's pack does not bundle `pulse`.** A `[pack] name = "assistant"` narrows the active
  set to that pack's own extensions, and `pulse` is not among them, so its skills never load and no
  boot refuses. The deploy's own pack above is the way through. A lockfile pinning `pulse` reaches
  it only with `[pack] name` unset, because the pack narrows the active set after the lockfile has
  filled it.
- **`ufoctl init` writes `ufo.toml` only when it is absent.** The pack line is a hand edit made
  once: a re-run leaves `[pack] name = "deploy"` exactly where it was and stops at
  `already initialized` before it reaches anything else. Nothing restores `assistant` over the
  deploy's own pack, and nothing reports the line is wrong either.
- **The assistant set does not hold `research` either.** It ships with ufo-core, so no install
  brings it in, and a pack naming `pulse` without it leaves a pulse turn nothing to gather through.
- **`research` owns a migration branch.** `ufoctl init` applies core's schema plus the active set's
  branches, and under `assistant` that set excludes `research`, so a deploy that changed
  `[pack] name` after init runs `ufoctl migrate` again before the next `ufoctl serve`.
- **A lockfile pins content, not installs.** Where a deploy pins its extension set rather than
  running everything discovered, the pin is a hash over the installed package's files:
  reinstalling the same content keeps it, and reinstalling changed content fails boot loud until
  the pin is rewritten.
- **Recall is empty rather than unavailable.** With no `UFO_OPENAI_API_KEY` nothing reaches the
  index, and the silence a pulse turn's opening `memory_search` returns is the same silence a new
  field returns. This is a missing key, not a business the member never stated — `field-pulse`'s
  step 1a only asks when the opening line *also* carries no business sentence; an unavailable index
  next to a populated opening line is this trap, not that one.
- **A turn with no carrier writes no ledger, and says so only in the brief.** The file tools are
  the client's, not an extension's: no manifest in the active set declares one, so a turn driven
  straight at the `ufo` surface over HTTP — no client attached, no `--remote` sandbox — has no
  filesystem at all. It still gathers, ranks and writes a full edition; it just cannot record what
  it published. The edition opens with a line about not being able to save files and the ledger is
  never created, so the next edition reads an empty ledger and repeats the last one. Drive a pulse
  through the `ufo` client or a `--remote` sandbox; a brief that looks right is not evidence the
  series does.
- **An armed gather keeps the rule it was set up under.** `task-scheduling` stores `field-pulse`'s
  manifest prompt on the scheduled row at apply time; editing the skill changes only what the next
  setup writes, not a row already armed. Re-applying `<field>-gather` upserts it in place and
  re-points its reporting to whichever conversation ran the re-apply, so adopting an edit means
  re-applying from the pulse's own conversation. An edit to `field-report` has no armed row to
  reach, and reaches the next edition the deploy's own `serve` process has booted for. Same family
  as #70's running `serve` process keeping the skills it booted with.
- **A running `serve` answers from the skills it booted with.** `ufoctl serve` resolves the active
  set at boot and materializes each skill into `$UFO_HOME/skills/<name>/`; every turn reads that
  copy. Editing the source reaches none of it, an editable install included, where the source the
  entry point resolves to is the working tree itself. The copy carries a recent mtime and reads as
  current, so the deploy quotes the old rule back with nothing in the log to say so. A `serve`
  restart picks the edit up and nothing else does. Same family as the armed row above (#66): a
  durable copy of instructions a later edit does not reach.

## Tests

```bash
pytest tests/
```

## License

Apache-2.0.
