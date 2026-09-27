"""The pulse pack's proof: its three skills parse into the registry with the dependency wiring that
makes the continuity and honesty contracts non-optional, and the covered ledger behaves as the
`brief-continuity` workflow describes.

The ledger tests run the module's own functions against a temporary `UFO_HOME`, so they assert the
file the next run actually reads rather than a fake.
"""

import json
from pathlib import Path

import pytest
import ufo_ext_pulse.manifest as pulse_manifest

from ufo.runtime.skills.runtime import parse_skill

SKILLS_ROOT = Path(pulse_manifest.__file__).parent / "skills"


def _skill(name: str):
    return parse_skill(SKILLS_ROOT / name)


def test_manifest_declares_three_skills_and_the_search_seam() -> None:
    manifest = pulse_manifest.manifest()
    assert manifest.name == "pulse"
    assert [spec.path.name for spec in manifest.skills] == [
        "field-pulse",
        "brief-continuity",
        "coverage-honesty",
    ]
    assert manifest.requires == ("search_providers",)
    assert manifest.tools == ()


@pytest.mark.parametrize("name", pulse_manifest.SKILL_NAMES)
def test_each_skill_parses_and_names_its_directory(name: str) -> None:
    skill = _skill(name)
    assert skill.name == name
    assert skill.description.startswith("Load when")
    assert skill.instructions.strip()


def test_every_declared_skill_path_exists() -> None:
    for spec in pulse_manifest.manifest().skills:
        assert (spec.path / "SKILL.md").is_file()


def test_field_pulse_pulls_both_contracts() -> None:
    """The contracts are wired, not remembered: a pulse run cannot load the workflow without them."""
    assert set(_skill("field-pulse").depends) == {"brief-continuity", "coverage-honesty"}


def test_continuity_ships_its_ledger_script() -> None:
    assert "covered.py" in dict(_skill("brief-continuity").files)


def test_field_pulse_routes_away_from_competitive_intel() -> None:
    assert "competitive-intel" in _skill("field-pulse").description


class TestCoveredLedger:
    @pytest.fixture(autouse=True)
    def _home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("UFO_HOME", str(tmp_path))
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "covered", SKILLS_ROOT / "brief-continuity" / "covered.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.covered = module

    def test_an_unwritten_series_reads_empty(self) -> None:
        assert self.covered.recent_rows("data-infra", 5) == []

    def test_a_recorded_story_is_found_in_span(self) -> None:
        self.covered.record("data-infra", "2026-09-21", "acme-1-0", "Acme 1.0", "https://x")
        assert self.covered.main(
            ["check", "--series", "data-infra", "--slug", "acme-1-0"]
        ) == 1

    def test_an_unrecorded_story_is_eligible(self) -> None:
        assert self.covered.main(
            ["check", "--series", "data-infra", "--slug", "nothing-yet"]
        ) == 0

    def test_the_span_is_counted_in_editions_not_days(self) -> None:
        """Five editions is five briefs the reader saw, whatever cadence produced them."""
        for day in range(20, 27):
            self.covered.record("data-infra", f"2026-09-{day}", f"s-{day}", "t", "")
        rows = self.covered.recent_rows("data-infra", 5)
        assert sorted({row["edition"] for row in rows}) == [
            "2026-09-22",
            "2026-09-23",
            "2026-09-24",
            "2026-09-25",
            "2026-09-26",
        ]

    def test_a_carried_story_keeps_one_slug_across_editions(self) -> None:
        self.covered.record("data-infra", "2026-09-21", "acme-1-0", "announced", "")
        self.covered.record("data-infra", "2026-09-25", "acme-1-0", "shipped", "")
        rows = [r for r in self.covered.recent_rows("data-infra", 5) if r["slug"] == "acme-1-0"]
        assert len(rows) == 2

    def test_the_ledger_is_append_only_jsonl(self) -> None:
        self.covered.record("data-infra", "2026-09-21", "acme-1-0", "Acme 1.0", "https://x")
        self.covered.record("data-infra", "2026-09-23", "beta-raise", "Beta raised", "")
        path = self.covered.ledger_path("data-infra")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert [row["slug"] for row in rows] == ["acme-1-0", "beta-raise"]

    @pytest.mark.parametrize(
        ("edition", "slug"),
        [("21-09-2026", "ok-slug"), ("2026-09-21", "Not A Slug"), ("2026-09-21", "trailing-")],
    )
    def test_malformed_identity_is_refused(self, edition: str, slug: str) -> None:
        with pytest.raises(ValueError):
            self.covered.record("data-infra", edition, slug, "t", "")

    def test_a_bad_series_name_is_refused(self) -> None:
        with pytest.raises(ValueError):
            self.covered.ledger_path("../escape")
