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

## The ledger

One JSON Lines file per series at `pulse/<series>.covered.jsonl` in the conversation workspace, one
row per story per edition, append-only. The path is workspace-relative and resolves against the
working directory a sandbox command starts in, so the file lands where the member can open it and
where a carrier that runs commands can write. A turn reaching the surface without one writes no
ledger at all — see Traps.

```bash
python "$UFO_HOME/skills/brief-continuity/covered.py" recent --series data-infra --editions 5
python "$UFO_HOME/skills/brief-continuity/covered.py" check --series data-infra --slug acme-1-0
```

`check` exits non-zero when the slug is covered in the span. A story carried again under the
material-new-development exception keeps its original slug, so the rows sharing a slug are that
story's history across the series.

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
  field returns.
- **A turn with no carrier writes no ledger, and says so only in the brief.** The file tools are
  the client's, not an extension's: no manifest in the active set declares one, so a turn driven
  straight at the `ufo` surface over HTTP — no client attached, no `--remote` sandbox — has no
  filesystem at all. It still gathers, ranks and writes a full edition; it just cannot record what
  it published. The edition opens with a line about not being able to save files and the ledger is
  never created, so the next edition reads an empty ledger and repeats the last one. Drive a pulse
  through the `ufo` client or a `--remote` sandbox; a brief that looks right is not evidence the
  series does.
- **An armed pulse keeps the rule it was set up under.** `task-scheduling` stores `field-pulse`'s
  manifest prompt on the scheduled row at apply time; editing the skill changes only what the next
  setup writes, not a row already armed. Re-applying `<field>-pulse` upserts it in place and
  re-points reporting to whichever conversation ran the re-apply, so adopting an edit means
  re-applying from the pulse's own conversation. Same family as #70's running `serve` process
  keeping the skills it booted with.

## Tests

```bash
pytest tests/
```

## License

Apache-2.0.
