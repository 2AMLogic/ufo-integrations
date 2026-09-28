# ufo-integrations

2AM Logic's extensions for [ufo](https://github.com/ufo-ai/ufo-core), the open-source business agent
operating system.

| Extension | What it adds |
| --- | --- |
| [`pulse`](extensions/pulse) | A recurring field brief that does not repeat itself and does not report silence it never observed |
| [`matrix`](extensions/matrix) | A Matrix chat surface: rooms as conversations, room members as members |

Each directory is one extension in ufo's sense — a Python package importing only `ufo.sdk`, declaring
one `ufo.extension` entry point. The repo ships them as a single distribution, the way ufo-core ships
its own, and a deploy activates them one at a time by name.

## Install

`ufo` is not on PyPI, so both it and this install from git:

```bash
pip install "ufo @ git+https://github.com/ufo-ai/ufo-core"
pip install "ufo-integrations @ git+https://github.com/2AMLogic/ufo-integrations"
```

Installing the distribution registers both `ufo.extension` entry points. Activating one is a separate
act: a deploy runs the extensions its active set names, and `ufoctl init` writes
`[pack] name = "assistant"`, which narrows that set to the extensions the assistant pack bundles.
Neither extension here is among them, so a deploy created that way installs both and runs neither,
and says nothing about it.

Each extension's README names what its own deploy needs: [`pulse`](extensions/pulse#install),
[`matrix`](extensions/matrix#install).

## Deploy notes

**OpenRouter-only deploys need a boot-probe workaround.** `ufoctl serve`'s boot-time
egress-key check (ufo-core's `model_rule_base`) only probes `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY`. A deploy whose only live model key is `OPENROUTER_API_KEY` — with no
Anthropic or OpenAI key set — satisfies neither, so boot fails with:

```
RuntimeError: no model provider key set; the sandbox would have no egress route
```

even though the model itself runs fine through the `openrouter` extension, since those calls are
host-side and never exercise the derived sandbox-egress rules.

Such a deploy satisfies the probe by naming the OpenRouter key where the probe reads the Anthropic
one, in `ufo.toml`:

```toml
[models]
anthropic_api_key_env = "OPENROUTER_API_KEY"   # probe-only; never spent
```

The allow-rule that produces is inert. Nothing is spent against Anthropic, because OpenRouter calls
never route through the sandbox egress proxy — so the setting answers the probe and changes nothing
else. A deploy holding a real Anthropic or OpenAI key needs none of it; the probe is already
satisfied.

The constraint and this workaround are recorded in
[#34](https://github.com/2AMLogic/ufo-integrations/issues/34). No upstream fix is tracked yet:
`ufo-core` still derives sandbox model egress from the Anthropic and OpenAI key envs alone.

## Tests

```bash
pytest extensions
```

The skill and ledger contracts need only `pytest` and `pyyaml` — they read the skills as the data on
disk that they are. `extensions/pulse/tests/test_registry.py` parses them through the real
`SkillRegistry` and skips where `ufo` is absent, so a fresh checkout still runs everything else. CI
runs both, the second against `ufo` at `main` on every change and nightly, which is what catches an
SDK change upstream. That job installs `pytest-xdist` beside `ufo`, whose test plugin requires it, and
fails if any test skips rather than runs.

A third job reads the migration lineage over the union of `main` and every open pull request. A
revision id is an identity two branches assign independently, and a clash is invisible from either
one: each branch is a sound chain alone, and the filenames differ, so the merge reports no conflict.
That union exists nowhere else, so the job turns a pull request red for a revision another open pull
request already claims, and the answer is to renumber against that claim rather than against `main`.
It holds a pull request that declares a migration of its own, which is every party to a collision and
nobody who can do nothing about one.

## License

Apache-2.0, matching ufo-core.
