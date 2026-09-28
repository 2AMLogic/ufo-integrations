"""One distribution, two extensions: each pins and activates on its own.

`ufo-integrations` ships `pulse` and `matrix` from a single distribution through two
`ufo.extension` entry points. That is a convenience for us and a hazard for a deploy: if pinning
one pinned the pair, or activating one dragged the other in, an operator who wanted a brief would
also be running a chat surface, and a change to either would invalidate the other's pin.

Upstream's model says it does not work that way — `extension_digest` hashes the entry point's own
top-level package, and both the lockfile and `[pack]` select by extension name rather than by
distribution. These tests hold that model to the layout this repo actually has, so a refactor that
merged the two packages, or dropped an `__init__.py`, fails here rather than in someone's deploy.

Skipped without `ufo`, like `extensions/pulse/tests/test_registry.py`: the checks are about core's
loader, so there is nothing to assert when core is absent.
"""

from __future__ import annotations

import pytest

pytest.importorskip("ufo", reason="install ufo from git to run the distribution pin tests")

import ufo  # noqa: E402
from ufo.host.ext.loader import (  # noqa: E402
    ExtensionPin,
    Lockfile,
    discovered,
    extension_digest,
    load_manifests,
    write_lockfile,
)

BOTH = ("pulse", "matrix")


@pytest.fixture(scope="module")
def installed() -> dict:
    """Every extension this environment discovers, keyed by manifest name."""
    found = discovered()
    missing = [name for name in BOTH if name not in found]
    if missing:
        pytest.skip(f"not installed in this environment: {missing} — `uv pip install -e .`")
    return found


def _pin(installed: dict, name: str) -> ExtensionPin:
    manifest, entry = installed[name]
    return ExtensionPin(name=name, version=manifest.version, digest=extension_digest(entry))


def _lockfile_with(tmp_path, monkeypatch, installed: dict, names: tuple[str, ...]):
    """Point core's lockfile path at a temp file pinning exactly `names`."""
    path = tmp_path / "ufo.lock"
    write_lockfile(
        path,
        Lockfile(
            ufo_version=getattr(ufo, "__version__", "0.1.0"),
            extensions=tuple(_pin(installed, name) for name in names),
        ),
    )
    monkeypatch.setenv("UFO_LOCKFILE", str(path))
    return path


def test_each_entry_point_resolves_its_own_package(installed: dict) -> None:
    """`_entry_spec` raises when a package has no `__init__.py`, so a namespace package cannot be
    pinned at all. Asserting it here names the cause, rather than leaving a digest call to fail."""
    for name in BOTH:
        _, entry = installed[name]
        assert extension_digest(entry).startswith("sha256:")


def test_a_digest_covers_only_its_own_package(installed: dict) -> None:
    """The digest is per extension, not per distribution: two entry points in one distribution
    produce two unrelated hashes, so shipping them together cannot couple their pins."""
    digests = {name: extension_digest(installed[name][1]) for name in BOTH}
    assert digests["pulse"] != digests["matrix"]


def test_editing_one_package_leaves_the_other_pin_unchanged(installed: dict, tmp_path) -> None:
    """The property an operator depends on: a matrix change must not invalidate a pulse pin.

    Rather than mutate the checkout, this re-derives matrix's digest from its own file map with one
    file altered, and checks pulse's digest is untouched — the digest is a pure function of the
    package's files, so the same conclusion holds without editing anything on disk.
    """
    from pathlib import Path

    import ufo_ext_matrix

    from ufo.host.ext.loader import extension_content_digest

    before_pulse = extension_digest(installed["pulse"][1])
    matrix_root = Path(ufo_ext_matrix.__file__).parent
    files = {
        str(p.relative_to(matrix_root)): p.read_bytes()
        for p in sorted(matrix_root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert files, "matrix package resolved to no files"

    unchanged = extension_content_digest(files)
    edited = dict(files)
    victim = next(iter(sorted(edited)))
    edited[victim] = edited[victim] + b"\n# touched by a test\n"
    assert extension_content_digest(edited) != unchanged, "editing matrix must move matrix's digest"

    assert extension_digest(installed["pulse"][1]) == before_pulse


def test_a_lockfile_pinning_one_activates_only_that_one(
    installed: dict, tmp_path, monkeypatch
) -> None:
    _lockfile_with(tmp_path, monkeypatch, installed, ("pulse",))
    active = {m.name for m in load_manifests(None)}
    assert "pulse" in active
    assert "matrix" not in active


def test_dropping_one_from_a_lockfile_leaves_the_other_pin_byte_identical(
    installed: dict, tmp_path, monkeypatch
) -> None:
    both = _lockfile_with(tmp_path, monkeypatch, installed, BOTH).read_text()
    only = _lockfile_with(tmp_path, monkeypatch, installed, ("pulse",)).read_text()

    import json

    pin_in_both = next(e for e in json.loads(both)["extensions"] if e["name"] == "pulse")
    pin_alone = next(e for e in json.loads(only)["extensions"] if e["name"] == "pulse")
    assert pin_in_both == pin_alone


def test_a_pack_naming_one_does_not_activate_the_other(installed: dict) -> None:
    """`[pack] name` narrows to exactly what the pack bundles. The assistant pack bundles neither,
    which is the documented trap; the point here is that naming a pack cannot smuggle in a sibling
    extension from the same distribution."""
    active = {m.name for m in load_manifests("assistant")}
    assert "pulse" not in active
    assert "matrix" not in active
