"""The manifest against the real runtime: the skills parse into the registry and the pack declares
what it says it declares. Skipped where `ufo` is not installed — it is not on PyPI, so a checkout
without it still runs every contract test beside this one."""

import pytest

pytest.importorskip("ufo", reason="install ufo from git to run the registry integration test")

import ufo_ext_pulse.manifest as pulse_manifest  # noqa: E402
from conftest import SKILL_NAMES, SKILLS_ROOT  # noqa: E402
from ufo.runtime.skills.runtime import parse_skill  # noqa: E402


def test_manifest_declares_three_skills_and_the_search_seam() -> None:
    manifest = pulse_manifest.manifest()
    assert manifest.name == "pulse"
    assert [spec.path.name for spec in manifest.skills] == list(SKILL_NAMES)
    assert manifest.requires == ("search_providers",)
    assert manifest.tools == ()


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
        "brief-continuity",
        "coverage-honesty",
    }


def test_the_runtime_carries_the_ledger_script_as_a_skill_file() -> None:
    assert "covered.py" in dict(parse_skill(SKILLS_ROOT / "brief-continuity").files)
