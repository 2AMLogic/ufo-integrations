"""The import boundaries upstream's extension gate enforces, checked here so a violation fails in
`pytest extensions` rather than on the next ufo release. Reads source with `ast` and needs no `ufo`.

| Rule | Applies to | Exempt |
| --- | --- | --- |
| Import `ufo` only through `ufo.sdk` | Every `.py` in an extension package | Files under `tests/` |
| Import nothing from `ufo` | Skill scripts: a `.py` below a `SKILL.md` directory | Nothing |
| No code in `__init__.py` | Every `__init__.py` | A module docstring |

Every extension package — `extensions/<name>/ufo_ext_<name>/` — is discovered, so a new extension is
covered the moment it lands.
"""

import ast
from pathlib import Path, PurePosixPath

import pytest

EXTENSIONS_ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".venv", "node_modules", "vendor", "dist", "__pycache__"}

SDK_ONLY = "imports ufo other than through ufo.sdk"
SKILL_SCRIPT = "skill script imports from ufo"
INIT_CODE = "__init__.py holds code other than a docstring"


def extension_packages() -> list[Path]:
    return sorted(p for p in EXTENSIONS_ROOT.glob("*/ufo_ext_*") if p.is_dir())


def package_sources() -> list[Path]:
    return sorted(
        path
        for package in extension_packages()
        for path in package.rglob("*.py")
        if not SKIP_DIRS.intersection(path.relative_to(EXTENSIONS_ROOT).parts)
    )


def is_test(relpath: PurePosixPath) -> bool:
    return "tests" in relpath.parts[:-1]


def is_skill_script(path: Path) -> bool:
    return any((parent / "SKILL.md").is_file() for parent in path.parents)


def ufo_imports(source: str) -> list[tuple[int, str]]:
    """Every absolute import of `ufo` or below, with its line. `from ufo import x` reports `ufo.x`,
    so `from ufo import sdk` reads as the core package it is imported from, not as `ufo.sdk`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
        else:
            continue
        found += [(node.lineno, m) for m in modules if m == "ufo" or m.startswith("ufo.")]
    return found


def is_sdk(module: str) -> bool:
    return module == "ufo.sdk" or module.startswith("ufo.sdk.")


def is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def violations(relpath: str, source: str, *, skill_script: bool) -> list[str]:
    """Every rule `source` breaks, as `path:lineno: rule (found 'module')`."""
    rel = PurePosixPath(relpath)
    found = []
    for lineno, module in ufo_imports(source):
        if skill_script:
            found.append(f"{rel}:{lineno}: {SKILL_SCRIPT} (found {module!r})")
        elif not is_test(rel) and not is_sdk(module):
            found.append(f"{rel}:{lineno}: {SDK_ONLY} (found {module!r})")
    if rel.name == "__init__.py":
        body = ast.parse(source).body
        if body and is_docstring(body[0]):
            body = body[1:]
        found += [f"{rel}:{node.lineno}: {INIT_CODE}" for node in body]
    return found


def test_an_extension_package_is_found() -> None:
    assert extension_packages(), "no extensions/*/ufo_ext_* package to gate"


def test_extension_packages_keep_upstream_boundaries() -> None:
    found = [
        v
        for path in package_sources()
        for v in violations(
            path.relative_to(EXTENSIONS_ROOT).as_posix(),
            path.read_text(),
            skill_script=is_skill_script(path),
        )
    ]
    assert not found, "\n".join(found)


MODULE = "pulse/ufo_ext_pulse/manifest.py"
SKILL = "pulse/ufo_ext_pulse/skills/brief-continuity/covered.py"
INIT = "pulse/ufo_ext_pulse/__init__.py"
TEST = "pulse/ufo_ext_pulse/tests/test_registry.py"


@pytest.mark.parametrize(
    ("relpath", "source", "skill_script", "expected"),
    [
        (
            MODULE,
            "from ufo.runtime import x\n",
            False,
            [f"{MODULE}:1: {SDK_ONLY} (found 'ufo.runtime')"],
        ),
        (MODULE, "import ufo.sdk.manifest\n", False, []),
        (MODULE, "from ufo.sdk.manifest import Manifest\n", False, []),
        (MODULE, "from ufo import sdk\n", False, [f"{MODULE}:1: {SDK_ONLY} (found 'ufo')"]),
        (MODULE, "import ufo\n", False, [f"{MODULE}:1: {SDK_ONLY} (found 'ufo')"]),
        (MODULE, "import ufology\nfrom . import ufo\n", False, []),
        (
            MODULE,
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import ufo.runtime\n",
            False,
            [f"{MODULE}:3: {SDK_ONLY} (found 'ufo.runtime')"],
        ),
        (
            MODULE,
            "import ufo.runtime\nimport ufo.sdk\nfrom ufo.core import y\n",
            False,
            [
                f"{MODULE}:1: {SDK_ONLY} (found 'ufo.runtime')",
                f"{MODULE}:3: {SDK_ONLY} (found 'ufo.core')",
            ],
        ),
        (SKILL, "import ufo\n", True, [f"{SKILL}:1: {SKILL_SCRIPT} (found 'ufo')"]),
        (SKILL, "from ufo.sdk import x\n", True, [f"{SKILL}:1: {SKILL_SCRIPT} (found 'ufo.sdk')"]),
        (SKILL, "import json\n", True, []),
        (INIT, "", False, []),
        (INIT, '"""The pulse extension."""\n', False, []),
        (INIT, '"""Doc."""\nVERSION = "1"\n', False, [f"{INIT}:2: {INIT_CODE}"]),
        (INIT, "import json\n", False, [f"{INIT}:1: {INIT_CODE}"]),
        (TEST, "from ufo.runtime.skills.runtime import parse_skill\n", False, []),
    ],
)
def test_violations(relpath: str, source: str, skill_script: bool, expected: list[str]) -> None:
    assert violations(relpath, source, skill_script=skill_script) == expected


def test_covered_is_classified_as_a_skill_script() -> None:
    assert is_skill_script(EXTENSIONS_ROOT / SKILL)
    assert not is_skill_script(EXTENSIONS_ROOT / MODULE)
