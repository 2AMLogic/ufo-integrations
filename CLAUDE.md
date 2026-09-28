# Working in ufo-integrations

This repo holds 2AM Logic's extensions for [ufo](https://github.com/ufo-ai/ufo-core). It is public
tooling: it puts no 2AM words in front of the world, and it is not a 2AM content surface.

## Upstream is the authority on shape

ufo-core's `spec.md`, `AGENTS.md`, and its own `extensions/` are the reference for how an extension
is built, and its house style is the one to write in. Before adding a skill or a seam, read the
sibling upstream already ships — `extensions/sample` exercises every manifest point, and
`extensions/research` is the template for a skill-only pack.

Two upstream rules this repo inherits and does not restate:

- **An extension imports only `ufo.sdk`.** A CI gate upstream forbids core internals in an
  extension, and code here that reaches past the SDK breaks on their next release.
- **Everything a member does happens in chat.** No slash command, no keyword, no bespoke end-user
  endpoint. `ufoctl` verbs are the operator surface, a different audience.

## Skills are the product, and they are prose

Most of what this repo ships is `SKILL.md` files, so the writing *is* the engineering. Match
upstream's register: declarative, one example rather than three, a table over a paragraph, budgets
where a field has a limit, and a closing `## Traps` listing the failure modes. No transition
language anywhere — no `legacy`, `deprecated`, `formerly`, `for now`, `v1`/`v2`, or `TODO`. Every file
reads as if designed this way from the start.

Frontmatter the runtime enforces, and `extensions/pulse/tests/test_skill_contracts.py` checks
without needing `ufo` installed:

| Field | Rule |
| --- | --- |
| `name` | Equals the directory name |
| `description` | Begins `Load when`, at most 50 words, names what the skill is *not* for |
| `metadata.depends` | The skills loaded alongside this one — the only mechanism that pulls another in |

A contract another skill must not skip belongs in `metadata.depends`, not in a sentence asking the
agent to remember it.

## What does not come into this repo

Nothing from `2AMLogic/marketing`'s `pulse/` beyond the craft. The published briefs are Tier 1, but
`strategy/pulse-design.md` is Tier 2 internal, and the ranker prompt cites Tier 2 benchmark
guardrails and a private research repo. Domain relevance lists, our sentinel claims, and our source
lists stay where they are — a generic skill wants the reader's own field filled in anyway, so none of
it was the reusable part. See the 2am workspace's `marketing/POSITIONING.md` for the tiers; do not
paraphrase them here.

This repo is `visibility: public` and `fleet: true`, so it binds the invention firewall: it may never
be open in a session with `notebook`. See the 2am workspace's `CLAUDE.md`.

## Tests

```bash
pytest extensions
```

Contract tests need only `pytest` and `pyyaml`. The registry test needs `ufo` from git and skips
without it — keep that split, so a checkout with no runtime still verifies the skills.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.

Work is coordinated through `loom:` labels on issues and pull requests, and the same roles run either under `loom-daemon` or by hand in an attended session — daemon mode is optional. Create the labels once with `.loom/scripts/sync-labels.sh` (an install ships `.github/labels.yml` but does not create the labels on the forge). A pull request ready for review carries `loom:review-requested`; Judge reviews it and applies `loom:pr` (approved) or `loom:changes-requested`; Doctor fixes a `loom:changes-requested` pull request and returns it to `loom:review-requested`. Only a `loom:pr` pull request gets merged, and always via this repo's merge script (`.loom/scripts/merge-pr.sh`) — never a raw forge merge command such as `gh pr merge`. Full state machine: `.loom/docs/label-state-machine.md`.
<!-- END LOOM ORCHESTRATION -->

<!-- BEGIN REPO-SKILLS -->
This repository has [Repo Skills](https://github.com/rjwalters/repo) v0.14.0 installed —
general repository hygiene and environment commands invoked as `/repo:<command>`. Run
`/repo:help` for the command list, or see `.claude/skills/repo/SKILL.md` for the full
guide. Hygiene commands apply safe, reversible fixes by default and report each
change; run with `--ask` to review first, and `--prune` to allow irreversible
removals. Managed by `install.sh` — edit outside the markers only.
<!-- END REPO-SKILLS -->
<!-- BEGIN SQUAD -->
## Squad — cross-agent collaboration

This repo has [Squad](https://github.com/rjwalters/squad) installed. Claude and
Codex share the same room and MCP tools. Before touching shared state, read
and follow the installed Squad skill, including its room/identity conventions:

- Claude: `.claude/skills/squad/SKILL.md`
- Codex: `.agents/skills/squad/SKILL.md` (invoke `$squad` or ask naturally)

Both expose join, goals, card, fanout, steward, and clear workflows. Claude aliases are
`/squad:<workflow>`; legacy Codex prompts are `/squad-<workflow>`.

For research work, discover and reuse the durable Science Card node IDs surfaced
by join/node list; the shared card workflow connects dependencies, committed
artifacts and revision-bound bank provenance.
<!-- END SQUAD -->
