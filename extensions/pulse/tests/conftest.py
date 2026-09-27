"""Shared locations. The skills are data on disk, so the contract tests read them directly and need
no `ufo` in the environment; only `test_registry.py` needs the runtime."""

import importlib.util
from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "ufo_ext_pulse" / "skills"
SKILL_NAMES = ("field-pulse", "brief-continuity", "coverage-honesty")


@pytest.fixture
def covered(tmp_path, monkeypatch):
    """The ledger module, loaded from the path a skill load puts it at, over a temporary UFO_HOME."""
    monkeypatch.setenv("UFO_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location(
        "covered", SKILLS_ROOT / "brief-continuity" / "covered.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
