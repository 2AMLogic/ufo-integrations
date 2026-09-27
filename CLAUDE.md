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
