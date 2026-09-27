"""The listener and the post against a fake homeserver: a stream resumes where it stood, the bot's
own echo and every non-message event found nothing, a declined ambient line and a non-member's line
found nothing, a room's audience only narrows, one bad event or one broken bot holds nothing else,
and a reply lands once however often it is posted."""

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import httpx
import pytest

pytest.importorskip("ufo", reason="install ufo from git to run the surface tests")

import sqlalchemy as sa  # noqa: E402

from matrix_fakes import (  # noqa: E402
    ALICE,
    BOB,
    BOT,
    DIRECT,
    OUTSIDER,
    ROOM,
    STRANGER,
    TOKEN,
    Homeserver,
    Listener,
    Workspace,
    batch,
    mention,
    on_loop,
    text,
)
from ufo.sdk.audience import foreign_room_audience, room_audience  # noqa: E402
from ufo.sdk.surfaces import (  # noqa: E402
    NOTHING_DELIVERED,
    SILENCE_SENTINEL,
    CredentialSlotUnset,
    SurfaceDeliveryError,
    SurfaceInstallationConflict,
    TerminalFrame,
    Writeback,
)
from ufo_ext_matrix.events import room_key, txn_id  # noqa: E402
from ufo_ext_matrix.since import read_since, write_since  # noqa: E402
from ufo_ext_matrix.surface import (  # noqa: E402
    CANCELLED_LINE,
    FAILED_LINE,
    HOMESERVER_SLOT,
    IDLE_SECONDS,
    TOKEN_SLOT,
    ConnectInput,
    Installation,
    MatrixSurface,
    ROSTER_LIMIT,
    installations,
)

ROOM_MEMBERS = [BOT, ALICE, BOB]
INTERNAL = room_audience("matrix", room_key(ROOM))
FOREIGN = foreign_room_audience("matrix", room_key(ROOM))


def rig(server: Homeserver, workspace: Workspace) -> Installation:
    surface = MatrixSurface(transport=server.transport, environ={})
    return Installation(surface, Listener(workspace), BOT)  # type: ignore[arg-type]


async def primed(server: Homeserver, workspace: Workspace) -> Installation:
    """An installation past its first sync, which only fixes where the stream stands."""
    server.members = {ROOM: ROOM_MEMBERS, DIRECT: [BOT, ALICE]}
    server.syncs.setdefault(None, batch("s1", {ROOM: [mention("$old", ALICE, "before")]}))
    installation = rig(server, workspace)
    assert await installation.step() == 0.0
    return installation


def writeback(terminal: TerminalFrame, turn_id: UUID | None = None) -> Writeback:
    return Writeback(
        turn_id=turn_id or uuid4(),
        conversation_id=uuid4(),
        agent_id=uuid4(),
        queue_key=ROOM,
        terminal=terminal,
        artifacts=(),
    )


@on_loop
async def test_the_first_sync_fixes_the_stream_and_founds_nothing(workspace: Workspace) -> None:
    server = Homeserver()
    await primed(server, workspace)
    assert workspace.admitted == []
    assert await read_since(workspace, BOT) == "s1"
    assert server.since_asked() == [None]


@on_loop
async def test_a_restart_resumes_without_replaying(workspace: Workspace) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$m1", ALICE, "summarize the week")]})
    installation = await primed(server, workspace)
    await installation.step()
    assert [a["key"] for a in workspace.admitted] == ["$m1"]
    assert await read_since(workspace, BOT) == "s2"

    restarted = rig(server, workspace)
    await restarted.step()
    assert server.since_asked() == [None, "s1", "s2"]
    assert [a["key"] for a in workspace.admitted] == ["$m1"]


@on_loop
async def test_a_replayed_batch_is_admitted_once(workspace: Workspace) -> None:
    """A crash after admitting but before the since write replays the batch; the event id is the
    admission's idempotency key, so the replay joins the turn it already founded."""
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$m1", ALICE, "again")]})
    installation = await primed(server, workspace)
    await installation.step()
    await write_since(workspace, BOT, "s1")
    await rig(server, workspace).step()
    assert server.since_asked() == [None, "s1", "s1"]
    assert len(workspace.admitted) == 1


@on_loop
async def test_the_bots_own_echo_founds_nothing(workspace: Workspace) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$echo", BOT, f"{BOT} said this")]})
    installation = await primed(server, workspace)
    await installation.step()
    assert workspace.admitted == []
    assert [h.line.own for h in installation.heard[ROOM]] == [False, True]


@pytest.mark.parametrize(
    "event",
    [
        {"type": "m.room.encrypted", "event_id": "$e", "sender": ALICE, "content": {}},
        {"type": "m.room.redaction", "event_id": "$r", "sender": ALICE, "redacts": "$m1"},
        mention("$edit", ALICE, "* fixed")
        | {
            "content": {
                "msgtype": "m.text",
                "body": "* fixed",
                "m.mentions": {"user_ids": [BOT]},
                "m.relates_to": {"rel_type": "m.replace", "event_id": "$m1"},
            }
        },
    ],
    ids=["encrypted", "redaction", "edit"],
)
@on_loop
async def test_non_messages_found_nothing(workspace: Workspace, event: dict) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [event]})
    installation = await primed(server, workspace)
    await installation.step()
    assert workspace.admitted == []
    assert await read_since(workspace, BOT) == "s2"


@on_loop
async def test_an_unaddressed_line_in_a_room_with_no_conversation_asks_nothing(
    workspace: Workspace,
) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [text("$lunch", ALICE, "lunch?")]})
    installation = await primed(server, workspace)
    await installation.step()
    assert workspace.asked == []
    assert workspace.admitted == []


@on_loop
async def test_a_declined_ambient_line_founds_no_turn(workspace: Workspace) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch(
        "s2", {ROOM: [mention("$m1", ALICE, "draft it"), text("$m2", BOB, "nice weather")]}
    )
    workspace.wanted = False
    installation = await primed(server, workspace)
    await installation.step()
    assert [a["key"] for a in workspace.admitted] == ["$m1"]
    [(asked, history)] = workspace.asked
    assert (asked.speaker, asked.text) == (BOB, "nice weather")
    assert [m.text for m in history] == ["before", "draft it"]


@on_loop
async def test_a_wanted_ambient_line_founds_a_turn_with_its_room_context(
    workspace: Workspace,
) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch(
        "s2",
        {
            ROOM: [
                mention("$m1", ALICE, "draft it"),
                text("$m2", BOB, "the deadline moved"),
                text("$m3", ALICE, "can you redo it for friday"),
            ]
        },
    )
    installation = await primed(server, workspace)
    await installation.step()
    assert [a["key"] for a in workspace.admitted] == ["$m1", "$m2", "$m3"]
    body = workspace.admitted[2]["body"]
    assert "can you redo it for friday" in body
    assert "draft it" not in body.split("<member_message")[0]


@on_loop
async def test_a_direct_room_is_addressed_and_links_its_member(workspace: Workspace) -> None:
    alice = workspace.members["alice@example.org"]
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {DIRECT: [text("$d1", ALICE, "what's on today")]})
    installation = await primed(server, workspace)
    await installation.step()
    [admitted] = workspace.admitted
    assert admitted["speaker"] == alice
    assert workspace.linked[ALICE] == alice
    assert workspace.conversations[DIRECT][1] == room_audience("matrix", room_key(DIRECT))
    assert workspace.asked == []


@on_loop
async def test_a_room_with_a_non_member_in_it_is_foreign(workspace: Workspace) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$m1", ALICE, "hi")]})
    server.syncs["s2"] = batch("s3", {ROOM: [mention("$m2", ALICE, "and again")]})
    installation = await primed(server, workspace)
    server.members[ROOM] = [*ROOM_MEMBERS, OUTSIDER]
    await installation.step()
    assert workspace.conversations[ROOM][1] == FOREIGN
    server.members[ROOM] = [*ROOM_MEMBERS, STRANGER]
    await installation.step()
    assert workspace.conversations[ROOM][1] == FOREIGN


@on_loop
async def test_a_stranger_on_the_bots_own_homeserver_makes_a_room_foreign(
    workspace: Workspace,
) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$m1", ALICE, "hi")]})
    installation = await primed(server, workspace)
    server.members[ROOM] = [*ROOM_MEMBERS, STRANGER]
    await installation.step()
    assert workspace.conversations[ROOM][1] == FOREIGN


@on_loop
async def test_a_workspace_with_no_domain_holds_only_foreign_rooms(workspace: Workspace) -> None:
    workspace.domain = None
    workspace.linked = {ALICE: uuid4(), BOB: uuid4()}
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$m1", ALICE, "hi")]})
    installation = await primed(server, workspace)
    await installation.step()
    assert workspace.conversations[ROOM][1] == FOREIGN


@on_loop
async def test_a_room_past_the_roster_limit_is_foreign_without_asking(
    workspace: Workspace,
) -> None:
    crowd = [f"@m{n}:example.org" for n in range(ROSTER_LIMIT)]
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$m1", ALICE, "hi")]})
    installation = await primed(server, workspace)
    server.members[ROOM] = [*ROOM_MEMBERS, *crowd]
    await installation.step()
    assert workspace.conversations[ROOM][1] == FOREIGN
    assert set(workspace.linked) == {ALICE}


@on_loop
async def test_a_rooms_audience_only_narrows_as_people_come_and_go(workspace: Workspace) -> None:
    """A direct room gains a member, then a non-member, who then leaves: the conversation stays
    one, goes foreign, and stays foreign — no step raises and every line is admitted."""
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {DIRECT: [text("$d1", ALICE, "just us")]})
    server.syncs["s2"] = batch("s3", {DIRECT: [mention("$d2", ALICE, "bob is here")]})
    server.syncs["s3"] = batch("s4", {DIRECT: [mention("$d3", ALICE, "carol too")]})
    server.syncs["s4"] = batch("s5", {DIRECT: [mention("$d4", ALICE, "carol left")]})
    installation = await primed(server, workspace)
    key = room_key(DIRECT)
    seen = []
    for joined in ([BOT, ALICE], [BOT, ALICE, BOB], [BOT, ALICE, BOB, OUTSIDER], [BOT, ALICE, BOB]):
        server.members[DIRECT] = joined
        assert await installation.step() == 0.0
        seen.append(workspace.conversations[DIRECT][1])
    internal, foreign = room_audience("matrix", key), foreign_room_audience("matrix", key)
    assert seen == [internal, internal, foreign, foreign]
    assert [a["key"] for a in workspace.admitted] == ["$d1", "$d2", "$d3", "$d4"]
    assert len({a["conversation_id"] for a in workspace.admitted}) == 1


@on_loop
async def test_a_non_member_founds_nothing_and_costs_nothing(workspace: Workspace) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch(
        "s2",
        {
            DIRECT: [text("$d1", STRANGER, "hello?")],
            ROOM: [mention("$m1", ALICE, "draft it"), text("$m2", OUTSIDER, "me too")],
        },
    )
    installation = await primed(server, workspace)
    server.members[DIRECT] = [BOT, STRANGER]
    await installation.step()
    assert [a["key"] for a in workspace.admitted] == ["$m1"]
    assert workspace.asked == []
    assert STRANGER not in workspace.linked
    assert await read_since(workspace, BOT) == "s2"


@on_loop
async def test_a_sender_off_the_workspace_domain_founds_nothing(workspace: Workspace) -> None:
    workspace.domain = "another.test"
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$m1", ALICE, "hi")]})
    installation = await primed(server, workspace)
    await installation.step()
    assert workspace.admitted == []
    assert workspace.conversations == {}


@on_loop
async def test_a_failing_event_is_skipped_and_the_stream_moves_on(
    workspace: Workspace, caplog: pytest.LogCaptureFixture
) -> None:
    workspace.broken = {"$bad"}
    server = Homeserver()
    server.syncs["s1"] = batch(
        "s2", {ROOM: [mention("$bad", ALICE, "boom"), mention("$ok", BOB, "fine")]}
    )
    installation = await primed(server, workspace)
    with caplog.at_level(logging.DEBUG):
        assert await installation.step() == 0.0
    assert [a["key"] for a in workspace.admitted] == ["$ok"]
    assert await read_since(workspace, BOT) == "s2"
    assert "matrix.message_skipped" in caplog.text
    assert "boom" not in caplog.text


async def _read_again_rather_than_skipped(workspace: Workspace, error: BaseException) -> None:
    """One database failure during admission: nothing admitted, and the position where it was."""
    workspace.lost = {"$gone": error}
    server = Homeserver()
    server.syncs["s1"] = batch("s2", {ROOM: [mention("$gone", ALICE, "hi")]})
    installation = await primed(server, workspace)
    before = await read_since(workspace, BOT)
    with pytest.raises(sa.exc.SQLAlchemyError):
        await installation.step()
    assert workspace.admitted == []
    assert await read_since(workspace, BOT) == before


@on_loop
async def test_a_dropped_connection_is_read_again_rather_than_skipped(
    workspace: Workspace,
) -> None:
    """A dropped connection reaches `admit` as `InterfaceError`, which is a sibling of
    `DatabaseError` and so never an `OperationalError`."""
    await _read_again_rather_than_skipped(
        workspace, sa.exc.InterfaceError("admit", None, OSError("connection lost"))
    )


@on_loop
async def test_an_exhausted_pool_is_read_again_rather_than_skipped(workspace: Workspace) -> None:
    """An exhausted pool reaches `admit` as `TimeoutError`, which reaches `SQLAlchemyError` without
    passing through `DBAPIError` at all. A guard narrowed to connection shapes drops it."""
    await _read_again_rather_than_skipped(workspace, sa.exc.TimeoutError("pool exhausted"))


@on_loop
async def test_a_gap_in_the_timeline_is_filled_from_history(workspace: Workspace) -> None:
    """A room that saw more than a sync's worth of events comes back `limited`; the missing messages
    are paged back from `prev_batch` to where the stream stood, and admitted oldest first."""
    server = Homeserver()
    cut = batch("s2", {ROOM: [mention("$m3", ALICE, "third")]})
    cut["rooms"]["join"][ROOM]["timeline"] |= {"limited": True, "prev_batch": "p2"}
    server.syncs["s1"] = cut
    server.history[(ROOM, "p2")] = {
        "chunk": [mention("$m2", BOB, "second"), mention("$m1", ALICE, "first")],
        "end": "p1",
    }
    server.history[(ROOM, "p1")] = {"chunk": [mention("$m3", ALICE, "third")], "end": "p0"}
    installation = await primed(server, workspace)
    await installation.step()
    assert [a["key"] for a in workspace.admitted] == ["$m1", "$m2", "$m3"]
    [asked] = [r for r in server.requests if r.url.path.endswith("/messages")][:1]
    assert (asked.url.params["dir"], asked.url.params["to"]) == ("b", "s1")


@on_loop
async def test_an_invite_from_the_home_server_is_joined(workspace: Workspace) -> None:
    def invited(room: str, sender: str) -> dict:
        member = {
            "type": "m.room.member",
            "state_key": BOT,
            "sender": sender,
            "content": {"membership": "invite"},
        }
        return {"invite_state": {"events": [member]}}

    server = Homeserver()
    server.syncs[None] = {
        "next_batch": "s1",
        "rooms": {
            "invite": {
                "!mine:example.org": invited("!mine:example.org", ALICE),
                "!theirs:elsewhere.test": invited("!theirs:elsewhere.test", OUTSIDER),
            }
        },
    }
    await primed(server, workspace)
    assert server.joined == ["!mine:example.org"]


@on_loop
async def test_an_invite_from_a_non_member_is_left_standing(workspace: Workspace) -> None:
    member = {
        "type": "m.room.member",
        "state_key": BOT,
        "sender": STRANGER,
        "content": {"membership": "invite"},
    }
    server = Homeserver()
    server.syncs[None] = {
        "next_batch": "s1",
        "rooms": {"invite": {"!trap:example.org": {"invite_state": {"events": [member]}}}},
    }
    await primed(server, workspace)
    assert server.joined == []


@on_loop
async def test_a_room_the_bot_was_removed_from_does_not_stall_the_stream(
    workspace: Workspace,
) -> None:
    server = Homeserver()
    server.syncs["s1"] = batch(
        "s2", {ROOM: [mention("$gone", ALICE, "hi")], DIRECT: [text("$d1", ALICE, "still here")]}
    )
    installation = await primed(server, workspace)
    server.forbidden = {ROOM}
    await installation.step()
    assert [a["key"] for a in workspace.admitted] == ["$d1"]
    assert await read_since(workspace, BOT) == "s2"


@on_loop
async def test_an_unbound_bot_waits_without_calling_out(workspace: Workspace) -> None:
    server = Homeserver()
    installation = Installation(
        MatrixSurface(transport=server.transport, environ={}),
        Listener(workspace, bound=frozenset()),  # type: ignore[arg-type]
        BOT,
    )
    assert await installation.step() == IDLE_SECONDS
    assert server.requests == []


@on_loop
async def test_an_empty_slot_waits_without_calling_out(workspace: Workspace) -> None:
    del workspace.credentials[TOKEN_SLOT]
    server = Homeserver()
    assert await rig(server, workspace).step() == IDLE_SECONDS
    assert server.requests == []


@on_loop
async def test_the_token_reaches_no_log(
    workspace: Workspace, caplog: pytest.LogCaptureFixture
) -> None:
    server = Homeserver(failure=httpx.Response(500, json={"errcode": "M_UNKNOWN"}))
    installation = rig(server, workspace)
    naps: list[float] = []

    async def nap(seconds: float) -> None:
        naps.append(seconds)
        if len(naps) == 2:
            raise RuntimeError("stop")

    installation.surface.sleep = nap
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError, match="stop"):
        await installation.run()
    assert naps == [1.0, 2.0]
    assert "matrix.sync_failed" in caplog.text
    assert TOKEN not in caplog.text
    assert TOKEN not in repr(installation.surface.client("https://hs.test", TOKEN))


@on_loop
async def test_one_broken_bot_backs_off_and_never_ends_the_listener(
    workspace: Workspace, caplog: pytest.LogCaptureFixture
) -> None:
    server = Homeserver()
    server.syncs[None] = {"rooms": {}}
    installation = rig(server, workspace)
    naps: list[float] = []

    async def nap(seconds: float) -> None:
        naps.append(seconds)
        if len(naps) == 3:
            raise asyncio.CancelledError

    installation.surface.sleep = nap
    with caplog.at_level(logging.DEBUG), pytest.raises(asyncio.CancelledError):
        await installation.run()
    assert naps == [1.0, 2.0, 5.0]
    assert caplog.text.count("matrix.sync_failed") == 3


@on_loop
async def test_losing_fleet_ownership_ends_the_stream(workspace: Workspace) -> None:
    server = Homeserver()
    installation = Installation(
        MatrixSurface(transport=server.transport, environ={}),
        Listener(workspace, owned=False),  # type: ignore[arg-type]
        BOT,
    )
    with pytest.raises(RuntimeError, match="fleet ownership"):
        await installation.run()
    assert server.requests == []


@on_loop
async def test_a_post_is_idempotent_under_its_turn(workspace: Workspace) -> None:
    server = Homeserver()
    surface = MatrixSurface(transport=server.transport, environ={})
    wb = writeback(TerminalFrame(status="done", text="The week in one line."))
    first = await surface.post(workspace, wb)  # type: ignore[arg-type]
    again = await surface.post(workspace, wb)  # type: ignore[arg-type]
    assert first == again == "$sent0"
    assert list(server.sent) == [txn_id(wb.turn_id)]
    assert server.sent[txn_id(wb.turn_id)]["body"] == "The week in one line."
    assert server.sent[txn_id(wb.turn_id)]["room"] == ROOM


@on_loop
async def test_silence_delivers_nothing(workspace: Workspace) -> None:
    server = Homeserver()
    surface = MatrixSurface(transport=server.transport, environ={})
    wb = writeback(TerminalFrame(status="done", text=SILENCE_SENTINEL))
    assert await surface.post(workspace, wb) is NOTHING_DELIVERED  # type: ignore[arg-type]
    assert server.requests == []


@on_loop
async def test_a_failed_turn_posts_the_surfaces_own_line(workspace: Workspace) -> None:
    server = Homeserver()
    surface = MatrixSurface(transport=server.transport, environ={})
    wb = writeback(TerminalFrame(status="failed", text="Traceback: secret internals"))
    await surface.post(workspace, wb)  # type: ignore[arg-type]
    assert server.sent[txn_id(wb.turn_id)]["body"] == FAILED_LINE


@pytest.mark.parametrize(
    ("text", "posted"),
    [
        ("I can only answer workspace members.", "I can only answer workspace members."),
        ("", CANCELLED_LINE),
    ],
    ids=["core-gave-a-reason", "stopped"],
)
@on_loop
async def test_a_cancelled_turn_posts_cores_reason(
    workspace: Workspace, text: str, posted: str
) -> None:
    server = Homeserver()
    surface = MatrixSurface(transport=server.transport, environ={})
    wb = writeback(TerminalFrame(status="cancelled", text=text))
    await surface.post(workspace, wb)  # type: ignore[arg-type]
    assert server.sent[txn_id(wb.turn_id)]["body"] == posted


@on_loop
async def test_a_rate_limit_carries_the_homeservers_wait(workspace: Workspace) -> None:
    server = Homeserver(
        failure=httpx.Response(429, json={"errcode": "M_LIMIT_EXCEEDED", "retry_after_ms": 2500})
    )
    surface = MatrixSurface(transport=server.transport, environ={})
    with pytest.raises(SurfaceDeliveryError) as raised:
        await surface.post(workspace, writeback(TerminalFrame(status="done", text="hi")))  # type: ignore[arg-type]
    assert raised.value.retry_after_seconds == 3
    assert TOKEN not in str(raised.value)


def test_the_deploy_names_its_bots_once_each() -> None:
    assert installations(f"{BOT}, @two:example.org {BOT}") == (BOT, "@two:example.org")
    assert installations("") == ()


@dataclass
class Credentials:
    values: dict[str, str]

    async def get(self, slot: str) -> str:
        if slot not in self.values:
            raise CredentialSlotUnset(slot)
        return self.values[slot]


@dataclass
class Installations:
    bound: list[tuple[str, str]] = field(default_factory=list)
    taken: bool = False

    async def bind(self, surface: str, installation_id: str) -> None:
        if self.taken:
            raise SurfaceInstallationConflict(surface)
        self.bound.append((surface, installation_id))


@dataclass
class Ext:
    credentials: Credentials
    installations: Installations = field(default_factory=Installations)


@dataclass
class Tool:
    ext: Ext


def connecting(values: dict[str, str], *, taken: bool = False) -> Tool:
    return Tool(Ext(Credentials(values), Installations(taken=taken)))


def said(result: object) -> str:
    return result.content[0].text  # type: ignore[attr-defined]


def test_connect_binds_the_bot_the_token_belongs_to() -> None:
    server = Homeserver()
    surface = MatrixSurface(transport=server.transport, environ={"UFO_MATRIX_BOTS": BOT})
    tool = connecting({HOMESERVER_SLOT: "https://matrix.example.org", TOKEN_SLOT: TOKEN})
    result = asyncio.run(surface.connect(tool, ConnectInput()))  # type: ignore[arg-type]
    assert not result.is_error
    assert tool.ext.installations.bound == [("matrix", BOT)]
    assert said(result) == f"Connected {BOT}. It is listening."


def test_connect_names_the_empty_slot_and_binds_nothing() -> None:
    server = Homeserver()
    surface = MatrixSurface(transport=server.transport, environ={})
    tool = connecting({HOMESERVER_SLOT: "https://matrix.example.org"})
    result = asyncio.run(surface.connect(tool, ConnectInput()))  # type: ignore[arg-type]
    assert TOKEN_SLOT in said(result)
    assert tool.ext.installations.bound == []
    assert server.requests == []


def test_connect_refuses_a_bad_token_without_repeating_it() -> None:
    server = Homeserver()
    surface = MatrixSurface(transport=server.transport, environ={})
    wrong = "syt_not_the_token"
    tool = connecting({HOMESERVER_SLOT: "https://matrix.example.org", TOKEN_SLOT: wrong})
    result = asyncio.run(surface.connect(tool, ConnectInput()))  # type: ignore[arg-type]
    assert result.is_error
    assert wrong not in said(result)
    assert tool.ext.installations.bound == []


def test_connect_refuses_a_bot_another_workspace_holds() -> None:
    server = Homeserver()
    surface = MatrixSurface(transport=server.transport, environ={})
    tool = connecting(
        {HOMESERVER_SLOT: "https://matrix.example.org", TOKEN_SLOT: TOKEN}, taken=True
    )
    result = asyncio.run(surface.connect(tool, ConnectInput()))  # type: ignore[arg-type]
    assert result.is_error
    assert "another workspace" in said(result)
