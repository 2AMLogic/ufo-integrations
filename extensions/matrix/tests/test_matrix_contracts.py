"""The rules the matrix surface holds without the runtime: what it may import, which events may
found a turn, the identifiers it derives, the messages it writes, and the frontmatter contract its
skill is loaded under. `events.py` and `messages.py` import neither `ufo` nor an HTTP client, and a
skill is data on disk, so these run on a checkout with only `pytest` and `pyyaml` installed."""

import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from ufo_ext_matrix.events import (
    SURFACE,
    TEXT_MSGTYPE,
    file_txn_id,
    gaps,
    invites,
    localpart,
    next_batch,
    part_txn_id,
    permalink,
    room_key,
    room_message,
    room_names,
    say_txn_id,
    server_name,
    timeline,
    txn_id,
)
from ufo_ext_matrix.messages import (
    EVENT_LIMIT_BYTES,
    FENCE,
    PART_BUDGET_BYTES,
    file_content,
    html_body,
    message_content,
    msgtype_for,
    parts,
    reply_relation,
)

EXTENSION = Path(__file__).resolve().parents[1]
PACKAGE = EXTENSION / "ufo_ext_matrix"
REPO = EXTENSION.parents[1]
SKILLS_ROOT = PACKAGE / "skills"
SKILL_NAMES = ("matrix-setup",)
DESCRIPTION_WORD_BUDGET = 50
THIRD_PARTY = frozenset({"httpx", "sqlalchemy", "alembic", "pydantic"})
TRANSITION_WORDS = re.compile(r"\b(legacy|deprecated|formerly|for now|TODO|v1|v2)\b", re.IGNORECASE)

BOT = "@ufo:example.org"
ROOM = "!room:example.org"
PURE = ("events.py", "messages.py")
ENVELOPE_BYTES = 2048


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


@pytest.mark.parametrize("module", PURE)
def test_the_contract_modules_import_nothing_installed(module: str) -> None:
    for name in imported_modules(PACKAGE / module):
        top, _, leaf = name.partition(".")
        if top == "ufo_ext_matrix":
            assert f"{leaf}.py" in PURE, name
        else:
            assert top in sys.stdlib_module_names, name


def test_the_package_declares_its_entry_point_and_client() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    assert project["entry-points"]["ufo.extension"]["matrix"] == "ufo_ext_matrix.manifest:manifest"
    assert any(dep.startswith("httpx") for dep in project["dependencies"])


def test_deploy_keys_are_bare_names_core_prefixes() -> None:
    """Core prefixes `UFO_` onto each deploy key itself (`ufo/cli.py` `_missing_deploy_keys`), so a
    key already carrying the prefix doubles — `ufoctl init` would name a `UFO_UFO_...` nobody
    should set. This suite installs no `ufo`, so it reads the manifest's source rather than the
    installed manifest."""
    tree = ast.parse((PACKAGE / "manifest.py").read_text())
    keys: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "Manifest":
            continue
        for keyword in node.keywords:
            if keyword.arg != "deploy_keys":
                continue
            assert isinstance(keyword.value, ast.Tuple), "the contract expects a literal tuple"
            for element in keyword.value.elts:
                assert isinstance(element, ast.Constant) and isinstance(element.value, str), (
                    "the contract expects literal deploy keys"
                )
                keys.append(element.value)
    assert keys, "the manifest declares no deploy_keys"
    assert all(not key.startswith("UFO_") for key in keys)


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
    headings = ("## What it adds", "## Install", "## Connect", "## Tests", "## License", "## Traps")
    for heading in headings:
        assert heading in readme


def frontmatter(name: str) -> dict:
    raw = (SKILLS_ROOT / name / "SKILL.md").read_text()
    assert raw.startswith("---"), f"{name}: SKILL.md must open with ---"
    _, meta, _ = raw.split("---", 2)
    return yaml.safe_load(meta)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_a_skill_name_matches_its_directory(name: str) -> None:
    assert frontmatter(name)["name"] == name


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_a_skill_description_routes(name: str) -> None:
    """The description is a routing budget: an over-long one loads the skill on the wrong turn, and
    one that does not say what the skill is not for loads it on a neighbouring ask."""
    description = frontmatter(name)["description"]
    assert description.startswith("Load when")
    assert len(description.split()) <= DESCRIPTION_WORD_BUDGET
    assert "Not for" in description


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_a_skill_wires_its_dependencies_rather_than_asking(name: str) -> None:
    """`metadata.depends` is the only mechanism that pulls another skill in, so it is declared even
    where this skill stands alone."""
    assert isinstance(frontmatter(name)["metadata"]["depends"], list)


@pytest.mark.parametrize("name", SKILL_NAMES)
def test_a_skill_closes_with_traps(name: str) -> None:
    _, _, body = (SKILLS_ROOT / name / "SKILL.md").read_text().split("---", 2)
    assert body.strip()
    assert "## Traps" in body


def test_setup_names_every_silence_a_misconfigured_bot_answers_with() -> None:
    """Each of the four presents only as the agent not answering, so a reader who has one of them and
    not this list has nothing to go on."""
    traps = (SKILLS_ROOT / "matrix-setup" / "SKILL.md").read_text().split("## Traps", 1)[1]
    for tell in ('[pack] name = "assistant"', "m.room.encrypted", "same user", "never invited"):
        assert tell in traps


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


def event_with_id(body: str, event_id: str) -> dict:
    return text_event(body) | {"event_id": event_id}


def test_a_cut_short_timeline_reads_its_gap_first_and_each_event_once() -> None:
    cut = {"limited": True, "prev_batch": "p1", "events": [event_with_id("c", "$c")]}
    whole = {"limited": False, "prev_batch": "p9", "events": [event_with_id("z", "$z")]}
    batch = {"rooms": {"join": {ROOM: {"timeline": cut}, "!calm:example.org": {"timeline": whole}}}}
    assert gaps(batch) == {ROOM: "p1"}
    earlier = {ROOM: [event_with_id("a", "$a"), event_with_id("b", "$b"), event_with_id("c", "$c")]}
    read = [(room, event["content"]["body"]) for room, event in timeline(batch, earlier)]
    assert read == [(ROOM, "a"), (ROOM, "b"), (ROOM, "c"), ("!calm:example.org", "z")]


def test_a_permalink_names_the_event() -> None:
    assert permalink(ROOM, "$abc") == "https://matrix.to/#/!room:example.org/$abc"


def test_a_threaded_message_carries_its_root() -> None:
    threaded = room_message(
        ROOM,
        text_event("in the thread", **{"m.relates_to": {"rel_type": "m.thread", "event_id": "$r"}}),
    )
    plain = room_message(ROOM, text_event("in the room"))
    assert threaded is not None and threaded.thread_root == "$r"
    assert plain is not None and plain.thread_root is None


def test_a_reply_relates_to_the_message_it_answers() -> None:
    assert reply_relation("$asked", None) == {"m.in_reply_to": {"event_id": "$asked"}}
    assert reply_relation("$asked", "$root") == {
        "rel_type": "m.thread",
        "event_id": "$root",
        "is_falling_back": True,
        "m.in_reply_to": {"event_id": "$asked"},
    }


def test_every_send_of_one_turn_has_its_own_transaction_id() -> None:
    turn = UUID("00000000-0000-4000-8000-000000000001")
    artifact = UUID("00000000-0000-4000-8000-00000000000a")
    reply = UUID("00000000-0000-4000-8000-00000000000b")
    ids = {
        part_txn_id(txn_id(turn), 1),
        part_txn_id(txn_id(turn), 2),
        file_txn_id(turn, artifact),
        say_txn_id(reply),
    }
    assert len(ids) == 4
    assert part_txn_id(txn_id(turn), 1) == txn_id(turn)
    assert file_txn_id(turn, artifact) == file_txn_id(turn, artifact)


@pytest.mark.parametrize(
    ("media_type", "msgtype"),
    [
        ("image/png", "m.image"),
        ("video/mp4", "m.video"),
        ("audio/ogg", "m.audio"),
        ("application/pdf", "m.file"),
        ("", "m.file"),
    ],
)
def test_a_file_is_sent_as_what_it_is(media_type: str, msgtype: str) -> None:
    assert msgtype_for(media_type) == msgtype


def test_a_file_message_carries_its_caption_and_its_name() -> None:
    captioned = file_content(
        "m.image", "chart.png", "Last week", "image/png", 12, "mxc://s/1", {"a": "b"}
    )
    bare = file_content("m.file", "notes.md", None, "text/markdown", 3, "mxc://s/2")
    assert captioned["body"] == "Last week" and captioned["filename"] == "chart.png"
    assert captioned["info"] == {"mimetype": "image/png", "size": 12}
    assert captioned["m.relates_to"] == {"a": "b"}
    assert bare["body"] == "notes.md" and "filename" not in bare
    assert "m.relates_to" not in bare


def test_a_message_carries_the_words_and_the_same_words_as_html() -> None:
    content = message_content("**now**", TEXT_MSGTYPE, {"m.in_reply_to": {"event_id": "$a"}})
    assert content["msgtype"] == TEXT_MSGTYPE
    assert content["body"] == "**now**"
    assert content["format"] == "org.matrix.custom.html"
    assert content["formatted_body"] == "<p><strong>now</strong></p>"
    assert content["m.relates_to"] == {"m.in_reply_to": {"event_id": "$a"}}
    assert "m.relates_to" not in message_content("hi", TEXT_MSGTYPE)


@pytest.mark.parametrize(
    ("markdown", "rendered"),
    [
        ("plain words", "<p>plain words</p>"),
        ("two\nlines", "<p>two<br />lines</p>"),
        (
            "**bold** and *thin* and _thin_",
            "<p><strong>bold</strong> and <em>thin</em> and <em>thin</em></p>",
        ),
        ("call `run()` first", "<p>call <code>run()</code> first</p>"),
        ("[the report](https://ufo.test/r)", '<p><a href="https://ufo.test/r">the report</a></p>'),
        (
            "[**bold link**](https://ufo.test)",
            '<p><a href="https://ufo.test"><strong>bold link</strong></a></p>',
        ),
        ("[nope](javascript:alert)", "<p>nope</p>"),
        ("## Heading", "<h2>Heading</h2>"),
        ("- one\n- two", "<ul><li>one</li><li>two</li></ul>"),
        ("1. one\n2. two", "<ol><li>one</li><li>two</li></ol>"),
        ("> quoted\n> again", "<blockquote>quoted<br />again</blockquote>"),
        ("a < b & c", "<p>a &lt; b &amp; c</p>"),
        (
            "```python\nx = 1 < 2\n```",
            '<pre><code class="language-python">x = 1 &lt; 2</code></pre>',
        ),
        ("```\nplain\n```", "<pre><code>plain</code></pre>"),
    ],
    ids=[
        "paragraph",
        "soft-break",
        "emphasis",
        "code-span",
        "link",
        "emphasis-in-link",
        "unfollowable-link",
        "heading",
        "bullets",
        "numbers",
        "quote",
        "escaped",
        "fence-with-language",
        "fence",
    ],
)
def test_markdown_renders_as_the_subset_matrix_names(markdown: str, rendered: str) -> None:
    assert html_body(markdown) == rendered


def test_a_reply_within_the_budget_is_one_message() -> None:
    reply = "First paragraph.\n\nSecond paragraph."
    assert parts(reply) == (reply,)
    assert parts("") == ("",)


def test_a_long_reply_splits_on_paragraph_boundaries() -> None:
    paragraph = "word " * 200
    reply = "\n\n".join(f"{n}. {paragraph}" for n in range(6))
    written = parts(reply)
    assert len(written) > 1
    assert "\n\n".join(written) == reply
    assert all(len(part.encode()) <= PART_BUDGET_BYTES for part in written)


def test_no_part_leaves_a_fence_open() -> None:
    code = "\n".join(f"line_{n} = {n}" for n in range(600))
    written = parts(f"Here it is.\n\n{FENCE}python\n{code}\n{FENCE}")
    assert len(written) > 1
    for part in written:
        assert part.count(FENCE) % 2 == 0, part[:80]
    assert all(FENCE not in part or part.strip().endswith(FENCE) for part in written)
    assert "line_599 = 599" in written[-1]


@pytest.mark.parametrize(
    "written",
    ['"' * 20000, "&" * 20000, '> "\n\n' * 4000, "- &\n" * 4000, "word" * 5000],
    ids=["quotes", "ampersands", "quoted-lines", "list-items", "one-long-word"],
)
def test_every_part_fits_one_event_however_it_expands(written: str) -> None:
    for part in parts(written):
        event = json.dumps(message_content(part, TEXT_MSGTYPE, reply_relation("$a", "$b")))
        assert len(event.encode()) + ENVELOPE_BYTES < EVENT_LIMIT_BYTES, len(event)
