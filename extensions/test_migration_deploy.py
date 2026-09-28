"""The lineage against a real deploy. `apply_migrations` with no pack layers core's version location
and every installed extension's into one run, so it is what reaches this repo's migrations: `ufoctl
migrate` narrows to the configured pack, and a deploy whose pack is another one applies nothing from
here and reports success. A duplicate revision id or a fork raises there before any DDL runs, and the
deploy stamps one row in `alembic_version` per branch, so each extension's directory contributes
exactly one of its own revisions as the head.

`test_migration_lineage.py` states the same property over the source alone, which is what a checkout
with no runtime can check. Skipped where `ufo` is not installed.
"""

import sqlite3

import pytest

pytest.importorskip("ufo", reason="install ufo from git to run the migration deploy test")

from test_migration_lineage import lineage, migration_dirs  # noqa: E402
from ufo.db import apply_migrations  # noqa: E402


@pytest.fixture(scope="module")
def heads(tmp_path_factory: pytest.TempPathFactory) -> set[str]:
    """Every revision a fresh SQLite deploy stamps: core's head and each extension branch's."""
    database = tmp_path_factory.mktemp("deploy") / "ufo.db"
    apply_migrations(f"sqlite+aiosqlite:///{database}")
    with sqlite3.connect(database) as connection:
        return {row[0] for row in connection.execute("select version_num from alembic_version")}


def test_the_deploy_reaches_one_head_per_extension(heads: set[str]) -> None:
    for directory in migration_dirs():
        declared = {fields.get("revision") for fields in lineage(directory).values()}
        stamped = sorted(revision for revision in declared if revision in heads)
        assert len(stamped) == 1, (
            f"{directory.parents[1].name}: {len(stamped)} of its revisions are heads "
            f"({', '.join(stamped) or 'none'}), out of {len(declared)} declared"
        )
