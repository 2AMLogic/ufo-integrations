"""One chain per extension, checked by reading the migration modules with `ast`, so it needs no
`ufo`. A revision id is an identity two branches assign independently, and nothing about a single
branch reveals a clash: the filenames differ, so the merge finds no conflict, and each branch is a
sound chain on its own. Alembic collapses two files claiming one id into one graph node, which wedges
the deploy after the second merge rather than on the pull request that introduced it.

| Fault | What it catches |
| --- | --- |
| Two files claim one revision | Two branches numbering the next migration alike |
| Two files chain onto one revision | A forked lineage, even where the revision ids differ |
| Two files start the lineage | The same fork, at the root |
| A file chains onto an unknown revision | A parent renamed or removed from under its child |
| No file starts the lineage | A cycle, which alembic cannot walk |

Unique revisions, unique parents, one root, and a known parent for every child make an extension's
declarations one chain, so a single head follows from them. `test_migration_deploy.py` asserts that
head against a real deploy.

`.github/workflows/ci.yml` runs this over the union of `main` and every open pull request, which is
the tree the second of two colliding branches merges into.
"""

import ast
from pathlib import Path

import pytest

EXTENSIONS_ROOT = Path(__file__).resolve().parent

NO_REVISION = "declares no revision"
NO_PARENT = "declares no down_revision"
DUPLICATE_REVISION = "two files claim revision"
FORKED = "two files chain onto revision"
TWO_ROOTS = "two files start the lineage"
UNKNOWN_PARENT = "chains onto a revision no file here declares"
NO_ROOT = "no file starts the lineage"

Lineage = dict[str, dict[str, str | None]]


def migration_dirs() -> list[Path]:
    return sorted(p for p in EXTENSIONS_ROOT.glob("*/ufo_ext_*/migrations") if p.is_dir())


def declarations(source: str) -> dict[str, str | None]:
    """Every module-level `name = "text"` or `name = None` in `source`, annotated or bare. A tuple
    or a call is not an identity, so `branch_labels` and anything computed are passed over."""
    found: dict[str, str | None] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        else:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str | None):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = value.value
    return found


def lineage(directory: Path) -> Lineage:
    """What each migration file in `directory` declares, by filename."""
    return {path.name: declarations(path.read_text()) for path in sorted(directory.glob("*.py"))}


def by_key(pair: tuple[str | None, list[str]]) -> tuple[bool, str]:
    """`None` is the root's parent and sorts before any revision it shares a lineage with."""
    return (pair[0] is not None, pair[0] or "")


def faults(extension: str, declared: Lineage) -> list[str]:
    """Every rule `extension`'s migrations break, as `extension[/file]: fault`."""
    found = []
    revisions: dict[str, list[str]] = {}
    parents: dict[str | None, list[str]] = {}
    for name, fields in sorted(declared.items()):
        revision = fields.get("revision")
        if not isinstance(revision, str):
            found.append(f"{extension}/{name}: {NO_REVISION}")
        elif "down_revision" not in fields:
            found.append(f"{extension}/{name}: {NO_PARENT}")
        else:
            revisions.setdefault(revision, []).append(name)
            parents.setdefault(fields["down_revision"], []).append(name)
    found += [
        f"{extension}: {DUPLICATE_REVISION} {revision!r} — {', '.join(names)}"
        for revision, names in sorted(revisions.items())
        if len(names) > 1
    ]
    for parent, names in sorted(parents.items(), key=by_key):
        if len(names) > 1:
            fault = TWO_ROOTS if parent is None else f"{FORKED} {parent!r}"
            found.append(f"{extension}: {fault} — {', '.join(names)}")
        if parent is not None and parent not in revisions:
            found += [f"{extension}/{name}: {UNKNOWN_PARENT} {parent!r}" for name in names]
    if revisions and None not in parents:
        found.append(f"{extension}: {NO_ROOT}")
    return found


def test_an_extension_ships_migrations() -> None:
    assert migration_dirs(), "no extensions/*/ufo_ext_*/migrations directory to gate"


def test_every_extension_declares_one_chain() -> None:
    found = [
        fault
        for directory in migration_dirs()
        for fault in faults(directory.parents[1].name, lineage(directory))
    ]
    assert not found, "\n".join(found)


def chain(*files: tuple[str, str | None, str | None]) -> Lineage:
    return {
        name: {"revision": revision, "down_revision": parent} for name, revision, parent in files
    }


SCHEMA = ("matrix_0001_schema.py", "matrix_0001", None)
LINKING = ("matrix_0002_linking.py", "matrix_0002", "matrix_0001")
CRYPTO = ("matrix_0002_crypto.py", "matrix_0002", "matrix_0001")
ANSWERING = ("matrix_0002_answering.py", "matrix_0002", "matrix_0001")


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        (chain(SCHEMA, LINKING), []),
        (chain(), []),
        (
            chain(SCHEMA, ANSWERING, CRYPTO, LINKING),
            [
                f"matrix: {DUPLICATE_REVISION} 'matrix_0002' — matrix_0002_answering.py, "
                "matrix_0002_crypto.py, matrix_0002_linking.py",
                f"matrix: {FORKED} 'matrix_0001' — matrix_0002_answering.py, "
                "matrix_0002_crypto.py, matrix_0002_linking.py",
            ],
        ),
        (
            chain(
                SCHEMA,
                LINKING,
                ("matrix_0003_answering.py", "matrix_0003", "matrix_0002"),
                ("matrix_0003_crypto.py", "matrix_0003", "matrix_0002"),
            ),
            [
                f"matrix: {DUPLICATE_REVISION} 'matrix_0003' — matrix_0003_answering.py, "
                "matrix_0003_crypto.py",
                f"matrix: {FORKED} 'matrix_0002' — matrix_0003_answering.py, matrix_0003_crypto.py",
            ],
        ),
        (
            chain(
                SCHEMA,
                LINKING,
                ("matrix_0003_answering.py", "matrix_0003", "matrix_0002"),
                ("matrix_0004_crypto.py", "matrix_0004", "matrix_0002"),
            ),
            [
                f"matrix: {FORKED} 'matrix_0002' — matrix_0003_answering.py, matrix_0004_crypto.py",
            ],
        ),
        (
            chain(SCHEMA, ("matrix_0002_linking.py", "matrix_0002", "matrix_0001_schema")),
            [
                f"matrix/matrix_0002_linking.py: {UNKNOWN_PARENT} 'matrix_0001_schema'",
            ],
        ),
        (
            chain(SCHEMA, ("matrix_0002_linking.py", "matrix_0002", None)),
            [f"matrix: {TWO_ROOTS} — matrix_0001_schema.py, matrix_0002_linking.py"],
        ),
        (
            chain(
                ("matrix_0001_schema.py", "matrix_0001", "matrix_0002"),
                ("matrix_0002_linking.py", "matrix_0002", "matrix_0001"),
            ),
            [f"matrix: {NO_ROOT}"],
        ),
        (
            {"matrix_0002_linking.py": {"down_revision": "matrix_0001"}},
            [f"matrix/matrix_0002_linking.py: {NO_REVISION}"],
        ),
        (
            {"matrix_0002_linking.py": {"revision": "matrix_0002"}},
            [f"matrix/matrix_0002_linking.py: {NO_PARENT}"],
        ),
    ],
)
def test_faults(declared: Lineage, expected: list[str]) -> None:
    assert faults("matrix", declared) == expected


def test_declarations_read_a_migration_module() -> None:
    source = (
        '"""matrix\'s tables."""\n'
        "import sqlalchemy as sa\n"
        'revision: str = "matrix_0001"\n'
        "down_revision: str | None = None\n"
        'branch_labels: tuple[str, ...] | None = ("matrix",)\n'
        'depends_on: str | None = "20260927025054"\n'
        "def upgrade() -> None:\n"
        '    revision = "not module level"\n'
    )
    assert declarations(source) == {
        "revision": "matrix_0001",
        "down_revision": None,
        "depends_on": "20260927025054",
    }
