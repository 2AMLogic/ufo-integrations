"""The rules `parse_skill_content` enforces, asserted without the runtime: a skill whose frontmatter
breaks one of these fails at boot, so it is worth catching in a test that needs nothing installed.

The description budget is a routing budget, not a style preference — an over-long description is what
makes a skill load on the wrong turn.
"""

import pytest
import yaml
from conftest import SKILL_NAMES, SKILLS_ROOT

DESCRIPTION_WORD_BUDGET = 50


def frontmatter(name: str) -> dict:
    raw = (SKILLS_ROOT / name / "SKILL.md").read_text()
    assert raw.startswith("---"), f"{name}: SKILL.md must open with ---"
    _, meta, _ = raw.split("---", 2)
    return yaml.safe_load(meta)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_name_matches_its_directory(name: str) -> None:
    assert frontmatter(name)["name"] == name


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_description_routes(name: str) -> None:
    description = frontmatter(name)["description"]
    assert description.startswith("Load when")
    assert len(description.split()) <= DESCRIPTION_WORD_BUDGET


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_body_is_present(name: str) -> None:
    _, _, body = (SKILLS_ROOT / name / "SKILL.md").read_text().split("---", 2)
    assert body.strip()


def test_field_pulse_pulls_both_contracts() -> None:
    """The contracts are wired, not remembered: a pulse run cannot load the workflow without them."""
    depends = frontmatter("field-pulse")["metadata"]["depends"]
    assert set(depends) == {"brief-continuity", "coverage-honesty"}


def test_field_pulse_routes_away_from_competitive_intel() -> None:
    """The two skills answer nearby asks, so the description has to say which one this is not."""
    assert "competitive-intel" in frontmatter("field-pulse")["description"]


def test_continuity_ships_its_ledger_script() -> None:
    assert (SKILLS_ROOT / "brief-continuity" / "covered.py").is_file()


def test_continuity_ships_its_pool_script() -> None:
    """SKILL.md invokes seen.py by path, exactly as it does covered.py. The argument for a script
    over a prose rule -- that staleness is a lookup rather than a recollection -- rests entirely on
    the script being there to look up."""
    assert (SKILLS_ROOT / "brief-continuity" / "seen.py").is_file()


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_every_skill_closes_with_traps(name: str) -> None:
    """House shape: the failure modes are listed where a reader looks for them."""
    assert "## Traps" in (SKILLS_ROOT / name / "SKILL.md").read_text()
