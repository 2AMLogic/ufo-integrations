"""What the pulse extension declares: four skills the agent loads on demand, and nothing else.

A recurring field brief is a series, not a report. `field-pulse` sets one up in chat, writes the
first brief in that turn and arms a daily gather; `field-report` writes every edition after it, from
the pool those gathers filled and without a search in the request path; `brief-continuity` holds the
covered ledger that makes the next brief carry what the last one did not, and the sightings pool the
report reads; `coverage-honesty` keeps a window nobody could read from being published as a window
where nothing happened.

The extension owns no tool, no schedule kind, and no store. Gathering is `research`'s, the recurring
row is `scheduled_tasks`', the feed entry is `report_digest`'s, and the ledger is a workspace file
the member can read. `requires` names the one seam a brief cannot be written without: a deploy with
pulse active and no search backend fails at boot rather than on the first fire."""

from pathlib import Path

from ufo.sdk.manifest import Manifest, SkillSpec

NAME = "pulse"
VERSION = "0.1.0"

SKILLS_ROOT = Path(__file__).parent / "skills"
SKILL_NAMES = ("field-pulse", "field-report", "brief-continuity", "coverage-honesty")


def manifest() -> Manifest:
    return Manifest(
        name=NAME,
        version=VERSION,
        skills=tuple(SkillSpec(path=SKILLS_ROOT / name) for name in SKILL_NAMES),
        requires=("search_providers",),
    )
