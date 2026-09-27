# ufo-integrations

2AM Logic's extensions for [ufo](https://github.com/ufo-ai/ufo-core), the open-source business agent
operating system.

| Extension | What it adds |
| --- | --- |
| [`pulse`](extensions/pulse) | A recurring field brief that does not repeat itself and does not report silence it never observed |
| `matrix` | A Matrix chat surface: rooms as conversations, room members as members |

Each directory is one extension in ufo's sense — a Python package importing only `ufo.sdk`, declaring
one `ufo.extension` entry point. The repo ships them as a single distribution, the way ufo-core ships
its own, and a deploy activates them one at a time by name.

## Install

`ufo` is not on PyPI, so both it and this install from git:

```bash
pip install "ufo @ git+https://github.com/ufo-ai/ufo-core"
pip install "ufo-integrations @ git+https://github.com/2AMLogic/ufo-integrations"
ufoctl ext install pulse
```

The entry point registers the pack; the next `ufoctl serve` loads it.

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

## License

Apache-2.0, matching ufo-core.
