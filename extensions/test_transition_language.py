"""The ban on transition language, checked over every extension tree so a violation fails in
`pytest extensions` and a new extension inherits it the moment it lands.

Every file reads as if designed this way from the start: no `legacy`, `deprecated`, `formerly`,
`for now`, `v1`/`v2` or `TODO` in any `.py` or `.md` file under `extensions/<name>/`. The wire
identifiers `searchable` strikes out are the one exception, and widening it is a visible choice, not
a side effect. This module names the vocabulary it bans, so it is the one file that reads itself
as exempt.
"""

import re
from pathlib import Path

import pytest

EXTENSIONS_ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".venv", "node_modules", "vendor", "dist", "__pycache__"}

TRANSITION_WORDS = re.compile(r"\b(legacy|deprecated|formerly|for now|TODO|v1|v2)\b", re.IGNORECASE)
PROTOCOL_NAMES = re.compile(r"\bm\.[a-z_]+(\.[a-z0-9_-]+)+")
WIRE_VERSIONS = re.compile(r'"v\d+"|/v\d+(?=[/"])|\.v\d+(?=")')


def extension_trees() -> list[Path]:
    return sorted(p.parent for p in EXTENSIONS_ROOT.glob("*/ufo_ext_*") if p.is_dir())


def prose_files() -> list[Path]:
    return sorted(
        path
        for tree in extension_trees()
        for path in tree.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".md"}
        and not SKIP_DIRS.intersection(path.relative_to(EXTENSIONS_ROOT).parts)
    )


def searchable(text: str) -> str:
    """`text` with the wire identifiers struck out, leaving the prose the ban is about.

    Two carve-outs, each scoped to a version this repo does not get to rename. `PROTOCOL_NAMES` is a
    dotted Matrix event or algorithm name — `m.olm.v1.curve25519-aes-sha2`, `m.megolm.v1.aes-sha2`.
    `WIRE_VERSIONS` is a version token a wire value carries: quoted on its own, which is how an
    `EncryptedFile` names its format (`"v": "v2"`), a segment of an endpoint's path, which is how a
    homeserver names its API (`/_matrix/client/v1/media`), or the tail of a quoted value, which is
    how the spec names a SAS MAC method (`"hkdf-hmac-sha256.v2"`).

    Each strikes to a space rather than to nothing, because removing a token joins what sat either
    side of it: `x"v1"legacy` collapses to `xlegacy` and passes a ban that `x legacy` fails.

    The boundary is the quoting, and it is honest about what that costs: a bare `v1` in a sentence
    fails, a backticked `v2` fails, and a version someone puts in double quotes mid-sentence passes.
    Reading a version out of a string literal is what writing the wire value looks like, and the
    narrower rule — knowing every way a constant or a JSON field might be spelled — would fail on
    the next spelling rather than on the next piece of transition language."""
    return WIRE_VERSIONS.sub(" ", PROTOCOL_NAMES.sub(" ", text))


@pytest.mark.parametrize(
    "path", prose_files(), ids=lambda p: p.relative_to(EXTENSIONS_ROOT).as_posix()
)
def test_no_transition_language(path: Path) -> None:
    if path == Path(__file__).resolve():
        return
    assert TRANSITION_WORDS.search(searchable(path.read_text())) is None, (
        f"{path.relative_to(EXTENSIONS_ROOT).as_posix()} carries transition language"
    )


def test_every_extension_tree_is_read() -> None:
    assert {t.name for t in extension_trees()} >= {"matrix", "pulse"}


def test_the_wire_carve_outs_do_not_launder_prose() -> None:
    """A carve-out that grows quietly is a ban that stopped holding, so **both** its edges are
    asserted rather than described.

    The right edge is the one that is easy to leave unpinned: a path version needs a slash before
    and a slash or quote after, and dropping that lookahead — or widening it to accept whitespace —
    turns `the /v1 rewrite` into prose the ban no longer reads."""
    passes = (
        'sealed = {"v": "v2"}',
        'ALGORITHM = "m.megolm.v1.aes-sha2"',
        'KEY = "A256CTR"',
        'MEDIA = "/_matrix/client/v1/media"',
    )
    fails = (
        "the v2 format",
        "the `v2` format",
        "kept for v1 readers",
        "a TODO here",
        'x"v1"legacy',
        "the /v1 rewrite",
        "dropped in /v1",
    )
    for source in passes:
        assert TRANSITION_WORDS.search(searchable(source)) is None, source
    for source in fails:
        assert TRANSITION_WORDS.search(searchable(source)) is not None, source
