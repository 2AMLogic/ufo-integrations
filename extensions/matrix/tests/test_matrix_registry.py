"""The manifest against the real runtime: the installed entry point loads through ufo's own loader,
the surface registers as durable, the setup action validates beside every builtin and addresses as the
`matrix` surface row's own, the skill parses into the registry, and the migration lands the since
table on a fresh database. Skipped where `ufo` is not installed."""

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("ufo", reason="install ufo from git to run the registry integration test")

from cryptography.fernet import Fernet  # noqa: E402

from ufo.db import apply_migrations  # noqa: E402
from ufo.host.ext.loader import (  # noqa: E402
    discovered,
    durable_surfaces,
    migration_locations,
    validate_ext_tools,
)
from ufo.host.kinds.surface_kind import registered_surfaces  # noqa: E402
from ufo.runtime.access.credentials import CredentialStore  # noqa: E402
from ufo.runtime.skills.runtime import parse_skill  # noqa: E402
from ufo.sdk.objects import SURFACE_KIND  # noqa: E402
from ufo_ext_matrix.manifest import CONNECT_TOOL, SKILL_NAMES  # noqa: E402
from ufo_ext_matrix.surface import BOTS_ENV, HOMESERVER_SLOT, TOKEN_SLOT  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parents[1] / "ufo_ext_matrix" / "migrations"


@pytest.fixture(scope="module")
def manifest():
    found = discovered()
    assert "matrix" in found, "install this repo (pip install -e .) so its entry point registers"
    return found["matrix"][0]


def test_the_entry_point_declares_one_durable_listening_surface(manifest) -> None:
    [surface] = manifest.surfaces
    assert surface.name == "matrix"
    assert surface.listen is not None and surface.post is not None
    assert surface.identify is not None
    assert surface.attach is None and surface.speak is None
    assert surface.routes == () and not surface.addressed
    assert durable_surfaces((manifest,)) == frozenset({"matrix"})
    assert registered_surfaces((manifest,))["matrix"].durable


def test_the_credentials_and_the_deploy_key(manifest) -> None:
    assert {slot.name for slot in manifest.credentials} == {HOMESERVER_SLOT, TOKEN_SLOT}
    assert all(slot.injection is None for slot in manifest.credentials)
    assert manifest.deploy_keys == (BOTS_ENV,)


def test_the_connect_tool_validates_beside_the_builtins(manifest) -> None:
    assert [tool.name for tool in manifest.tools] == [CONNECT_TOOL]
    validate_ext_tools((manifest,), CredentialStore(Fernet(Fernet.generate_key())))


def test_connect_is_an_instance_action_on_the_matrix_surface_row(manifest) -> None:
    """Setup belongs to the surface it sets up: core offers the action on the `matrix` row alone and
    refuses any other target, so no turn holds it as a tool of its own."""
    [tool] = manifest.tools
    assert tool.bound is not None
    assert (tool.bound.kind, tool.bound.binding, tool.bound.name) == (
        SURFACE_KIND,
        "instance",
        "matrix",
    )
    assert tool.canonical_id == f"action:{SURFACE_KIND}:{CONNECT_TOOL}"
    assert tool.side_effecting


def test_the_manifest_ships_its_setup_skill(manifest) -> None:
    assert tuple(spec.path.name for spec in manifest.skills) == SKILL_NAMES
    for spec in manifest.skills:
        skill = parse_skill(spec.path)
        assert skill.name == spec.path.name
        assert skill.instructions.strip()
        assert skill.depends == ()


def test_the_loader_finds_the_migrations() -> None:
    assert str(MIGRATIONS) in {str(Path(p).resolve()) for p in migration_locations()}


def test_the_migration_creates_the_since_table(tmp_path: Path) -> None:
    database = tmp_path / "ufo.db"
    apply_migrations(f"sqlite+aiosqlite:///{database}")
    with sqlite3.connect(database) as connection:
        columns = [row[1] for row in connection.execute("pragma table_info(matrix_ext_since)")]
    assert columns == ["workspace_id", "installation_id", "since", "updated_at"]
