"""The rules the matrix surface holds without the runtime: what it may import, which events may found
a turn, and the identifiers it derives. `events.py` imports neither `ufo` nor an HTTP client, so
these run on a checkout with only `pytest` installed."""

import ast
import re
import sys
import tomllib
from pathlib import Path
from uuid import UUID

import pytest

from ufo_ext_matrix.events import (
    SURFACE,
    invites,
    localpart,
    next_batch,
    permalink,
    room_key,
    room_message,
    room_names,
    server_name,
    timeline,
    txn_id,
)

EXTENSION = Path(__file__).resolve().parents[1]
PACKAGE = EXTENSION / "ufo_ext_matrix"
REPO = EXTENSION.parents[1]
THIRD_PARTY = frozenset({"httpx", "sqlalchemy", "alembic", "pydantic"})
TRANSITION_WORDS = re.compile(
    r"\b(legacy|deprecated|formerly|for now|TODO|v1|v2)\b", re.IGNORECASE
)

BOT = "@ufo:example.org"
ROOM = "!room:example.org"


def text_event(body: str = "hello", **content: object) -> dict:
    return {
        "type": "m.room.message",
        "event_id": "$one",
        "sender": "@alice:example.org",
        "content": {"msgtype": "m.text", "body": body, **content},
    }


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize(
    "path", sorted(PACKAGE.rglob("*.py")), ids=lambda p: str(p.relative_to(PACKAGE))
)
def test_imports_only_the_sdk(path: Path) -> None:
    """Upstream gates extensions on `ufo.sdk`; a reach past it breaks on the next release."""
    for name in imported_modules(path):
        top = name.split(".")[0]
        if top == "ufo":
            assert name == "ufo.sdk" or name.startswith("ufo.sdk."), name
        else:
            assert top in sys.stdlib_module_names | THIRD_PARTY | {"ufo_ext_matrix"}, name


def test_events_import_nothing_installed() -> None:
    for name in imported_modules(PACKAGE / "events.py"):
        assert name.split(".")[0] in sys.stdlib_module_names, name


def test_the_package_declares_its_entry_point_and_client() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    assert project["entry-points"]["ufo.extension"]["matrix"] == "ufo_ext_matrix.manifest:manifest"
    assert any(dep.startswith("httpx") for dep in project["dependencies"])


@pytest.mark.parametrize(
    "path",
    sorted(p for p in EXTENSION.rglob("*") if p.suffix in {".py", ".md"}),
    ids=lambda p: str(p.relative_to(EXTENSION)),
)
def test_no_transition_language(path: Path) -> None:
    if path.name == "test_matrix_contracts.py":
        return
    assert TRANSITION_WORDS.search(path.read_text()) is None


def test_readme_matches_the_pack_shape() -> None:
    readme = (EXTENSION / "README.md").read_text()
    for heading in ("## What it adds", "## Install", "## Tests", "## License", "## Traps"):
        assert heading in readme


def test_a_plain_text_message_is_a_member_message() -> None:
    message = room_message(ROOM, text_event("hi there"))
    assert message is not None
    assert (message.room_id, message.event_id, message.sender, message.body) == (
        ROOM,
        "$one",
        "@alice:example.org",
        "hi there",
    )


@pytest.mark.parametrize(
    "event",
    [
        {**text_event(), "type": "m.room.encrypted", "content": {"algorithm": "m.megolm.v1"}},
        {**text_event(), "type": "m.room.redaction", "redacts": "$zero", "content": {}},
        text_event("* fixed", **{"m.relates_to": {"rel_type": "m.replace", "event_id": "$zero"}}),
        text_event("* fixed", **{"m.new_content": {"msgtype": "m.text", "body": "fixed"}}),
        {**text_event(), "unsigned": {"redacted_because": {"type": "m.room.redaction"}}},
        {**text_event(), "content": {"msgtype": "m.notice", "body": "a bot's line"}},
        {**text_event(), "content": {}},
        text_event("   "),
        {**text_event(), "state_key": ""},
    ],
    ids=[
        "encrypted",
        "redaction",
        "edit",
        "new-content",
        "redacted",
        "notice",
        "redacted-content",
        "blank",
        "state",
    ],
)
def test_what_founds_no_turn(event: dict) -> None:
    assert room_message(ROOM, event) is None


def test_a_mention_addresses_the_bot() -> None:
    intentional = room_message(ROOM, text_event("hey", **{"m.mentions": {"user_ids": [BOT]}}))
    pill = room_message(
        ROOM,
        text_event("ufo: hey", formatted_body=f'<a href="https://matrix.to/#/{BOT}">ufo</a>: hey'),
    )
    unaddressed = room_message(ROOM, text_event("lunch?"))
    assert intentional is not None and intentional.addresses(BOT)
    assert pill is not None and pill.addresses(BOT)
    assert unaddressed is not None and not unaddressed.addresses(BOT)


def test_a_room_key_is_stable_and_colon_free() -> None:
    assert room_key(ROOM) == room_key(ROOM)
    assert room_key(ROOM) != room_key("!other:example.org")
    assert ":" not in room_key(ROOM)


def test_a_turn_sends_under_one_transaction_id() -> None:
    turn = UUID("00000000-0000-4000-8000-000000000001")
    assert txn_id(turn) == txn_id(UUID(str(turn)))
    assert txn_id(turn) != txn_id(UUID("00000000-0000-4000-8000-000000000002"))


def test_identifier_halves() -> None:
    assert server_name(BOT) == "example.org"
    assert server_name("@a:host:8448") == "host:8448"
    assert localpart(BOT) == "ufo"
    with pytest.raises(ValueError):
        server_name("nobody")
    assert SURFACE == "matrix"


def test_a_batch_reads_in_order() -> None:
    batch = {
        "next_batch": "s2",
        "rooms": {
            "join": {
                ROOM: {
                    "state": {"events": [{"type": "m.room.name", "content": {"name": "Ops"}}]},
                    "timeline": {"events": [text_event("a"), text_event("b")]},
                }
            },
            "invite": {
                "!new:example.org": {
                    "invite_state": {
                        "events": [
                            {
                                "type": "m.room.member",
                                "state_key": BOT,
                                "sender": "@alice:example.org",
                                "content": {"membership": "invite"},
                            }
                        ]
                    }
                }
            },
        },
    }
    assert [event["content"]["body"] for _, event in timeline(batch)] == ["a", "b"]
    assert room_names(batch) == {ROOM: "Ops"}
    assert list(invites(batch, BOT)) == [("!new:example.org", "@alice:example.org")]
    assert next_batch(batch) == "s2"
    with pytest.raises(ValueError):
        next_batch({})


def test_a_permalink_names_the_event() -> None:
    assert permalink(ROOM, "$abc") == "https://matrix.to/#/!room:example.org/$abc"
