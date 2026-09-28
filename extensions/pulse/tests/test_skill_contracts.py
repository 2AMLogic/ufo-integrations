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


def test_field_pulse_pulls_the_writer_and_both_contracts() -> None:
    """Wired, not remembered. A setup turn cannot reach its first edition without the skill that
    writes every edition, and neither skill can be loaded without the two contracts."""
    depends = frontmatter("field-pulse")["metadata"]["depends"]
    assert set(depends) == {"field-report", "brief-continuity", "coverage-honesty"}


def test_field_report_pulls_both_contracts() -> None:
    depends = frontmatter("field-report")["metadata"]["depends"]
    assert set(depends) == {"brief-continuity", "coverage-honesty"}


def test_field_pulse_routes_away_from_competitive_intel() -> None:
    """The two skills answer nearby asks, so the description has to say which one this is not."""
    assert "competitive-intel" in frontmatter("field-pulse")["description"]


def test_field_report_routes_away_from_setting_a_pulse_up() -> None:
    """Setting a pulse up and reading an edition of one are the nearby asks here, and routing to the
    wrong one either re-asks a member for sources they confirmed or skips the ask entirely."""
    assert "field-pulse" in frontmatter("field-report")["description"]


def test_the_report_reads_the_pool_by_script() -> None:
    """The report's whole claim -- that it publishes without searching -- rests on it reading the
    pool a gather filled, so the file has to invoke the pool script rather than describe it."""
    assert "seen.py" in (SKILLS_ROOT / "field-report" / "SKILL.md").read_text()


def scheduled_manifest() -> dict:
    """The one YAML block in field-pulse: the task a setup turn applies."""
    body = (SKILLS_ROOT / "field-pulse" / "SKILL.md").read_text()
    block = body.split("```yaml", 1)[1].split("```", 1)[0]
    return yaml.safe_load(block)


def test_the_scheduled_task_gathers_and_nothing_else() -> None:
    """The split is only real if the armed row cannot publish. A fire that ranked, wrote a file or
    recorded the ledger would be the fused run again, and its ledger rows would make every story in
    it ineligible for the edition the member did ask for."""
    manifest = scheduled_manifest()
    assert manifest["name"].endswith("-gather")
    prompt = manifest["spec"]["prompt"]
    assert "seen.py" in prompt
    assert "research-report" not in prompt
    assert "covered.py" not in prompt
    assert "run_now" not in manifest["spec"]


def test_the_daily_gather_is_bounded() -> None:
    """`task-scheduling` bounds a task that fires daily or more often with an `expires_at`, and an
    unbounded one keeps paying for search after the member has stopped reading it."""
    spec = scheduled_manifest()["spec"]
    assert spec["schedule"].split() == ["0", "12", "*", "*", "*"]
    assert "expires_at" in spec


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
