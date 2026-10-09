"""The frontmatter rules the runtime enforces on a skill, asserted once over every extension's
skills so a new extension inherits them the moment it lands.

A skill whose frontmatter breaks one of these fails at boot or loads on the wrong turn, so it is
worth catching in a test that needs only `pytest` and `pyyaml`. What a particular skill says, and
which skills it pulls, stays in that extension's own tests.
"""

from pathlib import Path

import pytest
import yaml

EXTENSIONS_ROOT = Path(__file__).resolve().parent
DESCRIPTION_WORD_BUDGET = 50


def skill_files() -> list[Path]:
    return sorted(EXTENSIONS_ROOT.glob("*/ufo_ext_*/skills/*/SKILL.md"))


def frontmatter(path: Path) -> dict:
    raw = path.read_text()
    assert raw.startswith("---"), f"{path.parent.name}: SKILL.md must open with ---"
    _, meta, _ = raw.split("---", 2)
    return yaml.safe_load(meta)


def depends(path: Path) -> list:
    """What the skill pulls in. A skill that declares no `metadata.depends` pulls nothing; one that
    declares it declares a list."""
    declared = (frontmatter(path).get("metadata") or {}).get("depends", [])
    assert isinstance(declared, list), f"{path.parent.name}: metadata.depends must be a list"
    return declared


def skill_id(path: Path) -> str:
    return path.relative_to(EXTENSIONS_ROOT).parent.as_posix()


def unresolved(path: Path, declared: list) -> list:
    """The names in `declared` that no other skill in the same extension provides."""
    siblings = {p.parent.name for p in skill_files() if p.parents[2] == path.parents[2]}
    return [name for name in declared if name not in siblings - {path.parent.name}]


SKILLS = pytest.mark.parametrize("path", skill_files(), ids=skill_id)


def test_every_extension_skill_is_read() -> None:
    assert {p.relative_to(EXTENSIONS_ROOT).parts[0] for p in skill_files()} >= {"matrix", "pulse"}


@SKILLS
def test_a_skill_name_matches_its_directory(path: Path) -> None:
    assert frontmatter(path)["name"] == path.parent.name


@SKILLS
def test_a_skill_description_routes(path: Path) -> None:
    """The description is a routing budget: an over-long one loads the skill on the wrong turn, and
    one that does not say what the skill is not for loads it on a neighbouring ask."""
    description = frontmatter(path)["description"]
    assert description.startswith("Load when")
    assert len(description.split()) <= DESCRIPTION_WORD_BUDGET
    assert "Not for" in description


@SKILLS
def test_a_skill_depends_on_skills_that_exist(path: Path) -> None:
    """`metadata.depends` is the only mechanism that pulls another skill in, so a name that matches
    no sibling drops a contract silently. Resolution stays inside one extension: a deploy activates
    extensions one at a time, so no skill can assume another extension's."""
    missing = unresolved(path, depends(path))
    assert not missing, f"{path.parent.name} depends on {missing}, which no sibling skill provides"


def test_a_skill_does_not_depend_on_itself() -> None:
    path = skill_files()[0]
    assert unresolved(path, [path.parent.name]) == [path.parent.name]
