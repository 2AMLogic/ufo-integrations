"""What the pulse extension declares: four skills the agent loads on demand, and the three calls
that keep a series' record alive when nobody is watching.

A recurring field brief is a series, not a report. `field-pulse` sets one up in chat, writes the
first brief in that turn and arms a daily gather; `field-report` writes every edition after it, from
the pool those gathers filled and without a search in the request path; `brief-continuity` holds the
covered ledger that makes the next brief carry what the last one did not, and the sightings pool the
report reads; `coverage-honesty` keeps a window nobody could read from being published as a window
where nothing happened.

**The store is this extension's own, and that is the whole of why it owns tools.** The ledger and
the pool began as workspace files, written by running a skill's script. A command tool belongs to
the terminal client, so a scheduled fire — the path a recurring brief actually runs on — wrote
nothing at all, and `brief-continuity`'s no-repeat rule governed a ledger no unattended edition had
ever added to (#120). The rows now land in two tables the extension's migration owns, reachable on
every fire; the files stay as a projection rendered from those tables, because a member can open a
file and cannot open a table.

Gathering is still `research`'s, the recurring row still `scheduled_tasks`', and the feed entry
still `report_digest`'s. `requires` names the one seam a brief cannot be written without: a deploy
with pulse active and no search backend fails at boot rather than on the first fire."""

from pathlib import Path

from ufo.sdk.manifest import Manifest, SkillSpec
from ufo.sdk.tools import ToolDef
from ufo_ext_pulse.tools import (
    RECALL_TOOL,
    RECORD_EDITION_TOOL,
    RECORD_SIGHTINGS_TOOL,
    RecallInput,
    RecordEditionInput,
    RecordSightingsInput,
    recall,
    record_edition,
    record_sightings,
)

NAME = "pulse"
VERSION = "0.2.0"

SKILLS_ROOT = Path(__file__).parent / "skills"
SKILL_NAMES = ("field-pulse", "field-report", "brief-continuity", "coverage-honesty")


def manifest() -> Manifest:
    return Manifest(
        name=NAME,
        version=VERSION,
        tools=(
            ToolDef(
                name=RECORD_SIGHTINGS_TOOL,
                description=(
                    "Record every lead a gather surfaced for a brief series, published or not, so "
                    "the next edition can tell a new development from a repeat. Send the whole "
                    "gather in one call."
                ),
                input_model=RecordSightingsInput,
                handler=record_sightings,
                side_effecting=True,
            ),
            ToolDef(
                name=RECORD_EDITION_TOOL,
                description=(
                    "Record the stories one edition of a brief series carried, so later editions "
                    "do not repeat them without a material new development."
                ),
                input_model=RecordEditionInput,
                handler=record_edition,
                side_effecting=True,
            ),
            ToolDef(
                name=RECALL_TOOL,
                description=(
                    "Read a brief series' record: the leads seen recently, the stories the last "
                    "few editions carried, or one lead's whole history when a slug is named."
                ),
                input_model=RecallInput,
                handler=recall,
            ),
        ),
        skills=tuple(SkillSpec(path=SKILLS_ROOT / name) for name in SKILL_NAMES),
        requires=("search_providers",),
    )
