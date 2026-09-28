"""The manifest against the real runtime: the skills parse into the registry, the three record
tools validate beside the builtins, and the migration this extension ships lands its two tables on a
real database. Skipped where `ufo` is not installed — it is not on PyPI, so a checkout without it
still runs every contract test beside this one."""

import inspect
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("ufo", reason="install ufo from git to run the registry integration test")

import ufo_ext_pulse.manifest as pulse_manifest  # noqa: E402
from conftest import SKILL_NAMES, SKILLS_ROOT  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from ufo.db import apply_migrations  # noqa: E402
from ufo.host.ext import loader  # noqa: E402
from ufo.host.ext.loader import migration_locations, validate_ext_tools  # noqa: E402
from ufo.runtime.access.credentials import CredentialStore  # noqa: E402
from ufo.runtime.skills.runtime import parse_skill  # noqa: E402
from ufo_ext_pulse import record  # noqa: E402
from ufo_ext_pulse.jobs import JOB_NAME, SCHEDULE  # noqa: E402
from ufo_ext_pulse.tools import (  # noqa: E402
    RECALL_TOOL,
    RECORD_EDITION_TOOL,
    RECORD_SIGHTINGS_TOOL,
)

MIGRATIONS = Path(__file__).resolve().parents[1] / "ufo_ext_pulse" / "migrations"


def test_manifest_declares_four_skills_and_the_search_seam() -> None:
    manifest = pulse_manifest.manifest()
    assert manifest.name == "pulse"
    assert [spec.path.name for spec in manifest.skills] == list(SKILL_NAMES)
    assert manifest.requires == ("search_providers",)


def test_the_three_record_tools_validate_beside_the_builtins() -> None:
    """The extension owns tools because the record has to be one record: a script writes to a path
    resolved against the turn's working directory, and a brief's carriers do not share one."""
    manifest = pulse_manifest.manifest()
    assert [tool.name for tool in manifest.tools] == [
        RECORD_SIGHTINGS_TOOL,
        RECORD_EDITION_TOOL,
        RECALL_TOOL,
    ]
    validate_ext_tools((manifest,), CredentialStore(Fernet(Fernet.generate_key())))


def test_the_two_writes_are_side_effecting_and_the_read_is_not() -> None:
    tools = {tool.name: tool for tool in pulse_manifest.manifest().tools}
    assert tools[RECORD_SIGHTINGS_TOOL].side_effecting
    assert tools[RECORD_EDITION_TOOL].side_effecting
    assert not tools[RECALL_TOOL].side_effecting


def test_no_record_tool_is_bound_to_an_object_row() -> None:
    """Recording is something a turn does wherever it runs, including a fire with no surface row to
    address — a binding would put the record behind an object the scheduled path never holds."""
    assert all(tool.bound is None for tool in pulse_manifest.manifest().tools)


def test_the_loader_finds_the_migrations() -> None:
    assert str(MIGRATIONS) in {str(Path(p).resolve()) for p in migration_locations()}


def test_the_migrations_create_the_extension_tables(tmp_path: Path) -> None:
    database = tmp_path / "ufo.db"
    apply_migrations(f"sqlite+aiosqlite:///{database}")
    with sqlite3.connect(database) as connection:

        def info(table: str) -> list[tuple[str, int]]:
            return [(row[1], row[5]) for row in connection.execute(f"pragma table_info({table})")]

        assert [name for name, _ in info("pulse_ext_sighting")] == [
            "workspace_id",
            "series",
            "seen",
            "slug",
            "url",
            "title",
            "source",
            "recorded_at",
        ]
        assert [name for name, _ in info("pulse_ext_covered")] == [
            "workspace_id",
            "series",
            "edition",
            "slug",
            "title",
            "url",
            "recorded_at",
        ]
        assert [name for name, _ in info("pulse_ext_series")] == [
            "workspace_id",
            "series",
            "conversation_id",
            "revision",
            "projected_revision",
            "updated_at",
        ]


def test_the_keys_are_natural_so_a_replayed_fire_records_once(tmp_path: Path) -> None:
    """The primary keys are the whole of why a retried or crash-replayed fire lands one row rather
    than a second copy. A surrogate key here would let every replay through, and the file this
    record projects to could never have caught it."""
    database = tmp_path / "ufo.db"
    apply_migrations(f"sqlite+aiosqlite:///{database}")
    with sqlite3.connect(database) as connection:

        def key(table: str) -> list[str]:
            rows = [row for row in connection.execute(f"pragma table_info({table})") if row[5]]
            return [row[1] for row in sorted(rows, key=lambda row: row[5])]

        assert key("pulse_ext_sighting") == ["workspace_id", "series", "seen", "slug", "url"]
        assert key("pulse_ext_covered") == ["workspace_id", "series", "edition", "slug"]


def test_every_declared_skill_path_exists() -> None:
    for spec in pulse_manifest.manifest().skills:
        assert (spec.path / "SKILL.md").is_file()


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_each_skill_parses(name: str) -> None:
    skill = parse_skill(SKILLS_ROOT / name)
    assert skill.name == name
    assert skill.instructions.strip()


def test_the_runtime_sees_the_dependency_wiring() -> None:
    assert set(parse_skill(SKILLS_ROOT / "field-pulse").depends) == {
        "field-report",
        "brief-continuity",
        "coverage-honesty",
    }
    assert set(parse_skill(SKILLS_ROOT / "field-report").depends) == {
        "brief-continuity",
        "coverage-honesty",
    }


def test_the_runtime_carries_the_ledger_script_as_a_skill_file() -> None:
    assert "covered.py" in dict(parse_skill(SKILLS_ROOT / "brief-continuity").files)


def test_the_runtime_carries_the_pool_script_as_a_skill_file() -> None:
    """A skill load has to materialise seen.py where SKILL.md says to run it, or every pool
    invocation in that file is a path to nothing."""
    assert "seen.py" in dict(parse_skill(SKILLS_ROOT / "brief-continuity").files)


def test_the_runtime_carries_the_coverage_script_as_a_skill_file() -> None:
    """Both halves of the coverage store travel with the skill: the script the gather runs and the
    shared mechanics it imports at the path the load materialises them at."""
    files = dict(parse_skill(SKILLS_ROOT / "brief-continuity").files)
    assert "coverage.py" in files
    assert "_jsonl_pool.py" in files


def test_the_projection_is_declared_as_a_job() -> None:
    """The projection is declared as a job, which is where `jobs.py` argues it belongs: the copy
    follows the series rather than the turn that recorded, no sandbox is opened per write, and a
    record that advanced with no workspace to take a file is rendered whole on a later tick."""
    manifest = pulse_manifest.manifest()
    assert [job.name for job in manifest.jobs] == [JOB_NAME]
    assert manifest.jobs[0].schedule == SCHEDULE
    assert callable(manifest.jobs[0].candidates)


def test_turn_tools_really_does_leave_a_tool_handler_without_the_file_seam() -> None:
    """Pinned against core rather than asserted in prose, because an earlier version of this change
    projected from a tool and the test that "covered" it used a fake that could write.

    `context_for` is the one builder, and `files` is `None` unless `sandboxes=` is passed; the whole
    of `turn_tools` never passes it. This is why `pulse_fakes.Store.files` defaults to `None` — it is
    *not* evidence that a tool cannot write a workspace file, which it can through
    `ctx.sandbox.write_file`. It bounds one seam, not the capability.
    """
    source = inspect.getsource(loader.turn_tools)
    assert "sandboxes" not in source


def test_the_job_asks_only_for_workspaces_holding_unprojected_work() -> None:
    """`ConversationFiles.write` opens a sandbox rather than reusing a live one, so a candidates
    select that named every workspace would start a container per pulse conversation per tick."""
    compiled = str(record.due_projections())
    assert "pulse_ext_series" in compiled
    assert "projected_revision" in compiled
    assert "sighting" not in compiled and "covered" not in compiled


def test_dueness_is_decided_by_a_counter_and_never_by_a_clock() -> None:
    """A wall-clock watermark is only as monotonic as the clock behind it. A write stamped earlier
    than a recorded projection reads as older than the file, and its rows stay out of the file
    permanently — reproduced before this changed. Pinned against the compiled select so a later
    edit cannot quietly reintroduce a time comparison."""
    compiled = str(record.due_projections())
    assert "updated_at" not in compiled
    # `projected_revision` contains "revision", so asserting the substring alone passes on a select
    # that names only the projection mark. Both columns have to be there for the comparison to be
    # the one described.
    assert "pulse_ext_series.revision" in compiled
    assert "pulse_ext_series.projected_revision" in compiled
