"""End-to-end encryption against a fake homeserver, with real Olm and Megolm on both ends: an
encrypted direct room round trips, a restart keeps its device and its sessions, an event that
arrives before its key is heard once the key lands and never as ciphertext, a post reaches every
member device and no departed one, a device that changes its keys is not believed, and the store
opens only under its slot's key."""

import logging
from uuid import uuid4

import pytest

pytest.importorskip("ufo", reason="install ufo from git to run the crypto tests")
pytest.importorskip("vodozemac", reason="install the matrix-e2ee extra to run the crypto tests")
pytest.importorskip("cryptography", reason="install the matrix-e2ee extra to run the crypto tests")

import sqlalchemy as sa  # noqa: E402
import vodozemac as vz  # noqa: E402
from crypto_fakes import BOT_DEVICE, MEGOLM, STORE_KEY, E2EHomeserver, Peer  # noqa: E402
from matrix_fakes import ALICE, BOB, BOT, DIRECT, ROOM, Listener, Workspace, batch, on_loop  # noqa: E402
from ufo.sdk.surfaces import SurfaceDeliveryError, TerminalFrame, Writeback  # noqa: E402
from ufo_ext_matrix import crypto  # noqa: E402
from ufo_ext_matrix.client import MatrixClient  # noqa: E402
from ufo_ext_matrix.crypto import STORE_KEY_SLOT, device_for  # noqa: E402
from ufo_ext_matrix.crypto_store import CRYPTO_TABLE, CryptoStore, Sealer, StoreLocked  # noqa: E402
from ufo_ext_matrix.events import txn_id  # noqa: E402
from ufo_ext_matrix.surface import HOMESERVER_SLOT, TOKEN_SLOT, Installation, MatrixSurface  # noqa: E402

ENCRYPTED = {"algorithm": MEGOLM}


def rig(server: E2EHomeserver, workspace: Workspace) -> Installation:
    """A fresh surface and installation, as a restarted process builds them."""
    surface = MatrixSurface(transport=server.transport, environ={})
    return Installation(surface, Listener(workspace), BOT)  # type: ignore[arg-type]


async def primed(server: E2EHomeserver, workspace: Workspace) -> Installation:
    """An installation past its first sync, which creates and publishes the bot's device."""
    workspace.credentials[STORE_KEY_SLOT] = STORE_KEY
    server.members.setdefault(ROOM, [BOT, ALICE, BOB])
    server.members.setdefault(DIRECT, [BOT, ALICE])
    server.syncs.setdefault(None, batch("s1"))
    installation = rig(server, workspace)
    assert await installation.step() == 0.0
    return installation


async def post(server: E2EHomeserver, workspace: Workspace, room_id: str, text: str) -> dict:
    wb = Writeback(
        turn_id=uuid4(),
        conversation_id=uuid4(),
        agent_id=uuid4(),
        queue_key=room_id,
        terminal=TerminalFrame(status="done", text=text),
        artifacts=(),
    )
    surface = MatrixSurface(transport=server.transport, environ={})
    await surface.post(workspace, wb)  # type: ignore[arg-type]
    return server.sent[txn_id(wb.turn_id)]


def ciphertexts(*events: dict) -> list[str]:
    return [e["content"]["ciphertext"] for e in events]


@on_loop
async def test_an_encrypted_direct_room_round_trips(workspace: Workspace) -> None:
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    installation = await primed(server, workspace)
    assert server.device_uploads == 1
    alice = Peer(server, ALICE, "ALICEPHONE")
    alice.share(DIRECT)
    said = alice.say(DIRECT, "$d1", "what's on today")
    server.syncs["s1"] = batch("s2", {DIRECT: [said]})
    await installation.step()

    [admitted] = workspace.admitted
    assert admitted["key"] == "$d1"
    assert "what's on today" in admitted["body"]
    assert ciphertexts(said)[0] not in admitted["body"]
    assert admitted["speaker"] == workspace.members["alice@example.org"]

    sent = await post(server, workspace, DIRECT, "Standup at ten.")
    assert sent["type"] == "m.room.encrypted"
    assert "body" not in sent and "Standup" not in str(sent)
    [room_key] = alice.read_inbox()
    assert room_key["type"] == "m.room_key" and room_key["sender"] == BOT
    payload = alice.decrypt(sent)
    assert payload["room_id"] == DIRECT
    assert payload["content"] == {"msgtype": "m.text", "body": "Standup at ten."}


@on_loop
async def test_the_bots_own_encrypted_echo_is_heard_as_its_own(workspace: Workspace) -> None:
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    installation = await primed(server, workspace)
    Peer(server, ALICE, "ALICEPHONE")
    sent = await post(server, workspace, DIRECT, f"{BOT} replying")
    echo = {"type": "m.room.encrypted", "event_id": sent["event_id"], "sender": BOT}
    echo["content"] = {k: v for k, v in sent.items() if k not in ("room", "event_id", "type")}
    server.syncs["s1"] = batch("s2", {DIRECT: [echo]})
    await installation.step()
    assert workspace.admitted == []
    assert [h.line.own for h in installation.heard[DIRECT]] == [True]
    assert not any(e["type"] == "m.room_key_request" for _, e in server.to_device_sent)


@on_loop
async def test_a_restart_keeps_the_device_and_its_sessions(workspace: Workspace) -> None:
    server = E2EHomeserver()
    server.encrypted[ROOM] = ENCRYPTED
    await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    alice.share(ROOM)
    server.syncs["s1"] = batch("s2")
    await rig(server, workspace).step()
    before = alice.say(ROOM, "$m1", f"{BOT} sent before the restart")

    restarted = rig(server, workspace)
    server.syncs["s2"] = batch("s3", {ROOM: [before]})
    await restarted.step()
    assert server.device_uploads == 1
    assert [a["key"] for a in workspace.admitted] == ["$m1"]

    alice.outbound.pop(ROOM)
    alice.share(ROOM)
    after = alice.say(ROOM, "$m2", f"{BOT} sent on a new session")
    server.syncs["s3"] = batch("s4", {ROOM: [after]})
    await rig(server, workspace).step()
    assert [a["key"] for a in workspace.admitted] == ["$m1", "$m2"]


@on_loop
async def test_an_event_before_its_key_is_heard_once_the_key_lands(
    workspace: Workspace,
) -> None:
    server = E2EHomeserver()
    server.encrypted[ROOM] = ENCRYPTED
    installation = await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    early = alice.say(ROOM, "$m1", f"{BOT} are you there")
    server.syncs["s1"] = batch("s2", {ROOM: [early]})
    await installation.step()
    assert workspace.admitted == []
    [request] = alice.read_inbox()
    assert request["type"] == "m.room_key_request"
    assert request["content"]["body"]["session_id"] == early["content"]["session_id"]

    alice.forward(ROOM)
    server.syncs["s2"] = batch("s3")
    server.syncs["s3"] = batch("s4", {ROOM: [early]})
    await installation.step()
    await installation.step()
    [admitted] = workspace.admitted
    assert admitted["key"] == "$m1"
    assert "are you there" in admitted["body"]
    assert ciphertexts(early)[0] not in admitted["body"]
    assert len(alice.read_inbox()) == 0


@on_loop
async def test_an_event_whose_key_never_comes_is_dropped(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    server = E2EHomeserver()
    server.encrypted[ROOM] = ENCRYPTED
    installation = await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    server.syncs["s1"] = batch("s2", {ROOM: [alice.say(ROOM, "$m1", f"{BOT} hello?")]})
    await installation.step()
    later = crypto.now_ms() + (crypto.PENDING_SECONDS + 1) * 1000
    monkeypatch.setattr(crypto, "now_ms", lambda: later)
    server.syncs["s2"] = batch("s3")
    with caplog.at_level(logging.DEBUG):
        await installation.step()
    assert "matrix.undecryptable_dropped" in caplog.text
    alice.share(ROOM)
    server.syncs["s3"] = batch("s4")
    await installation.step()
    assert workspace.admitted == []


@on_loop
async def test_a_post_reaches_every_member_device_and_no_departed_one(
    workspace: Workspace,
) -> None:
    server = E2EHomeserver()
    server.encrypted[ROOM] = ENCRYPTED
    await primed(server, workspace)
    phone = Peer(server, ALICE, "ALICEPHONE")
    laptop = Peer(server, ALICE, "ALICELAPTOP")
    bob = Peer(server, BOB, "BOBPHONE")
    peers = (phone, laptop, bob)

    first = await post(server, workspace, ROOM, "First.")
    for peer in peers:
        assert [p["type"] for p in peer.read_inbox()] == ["m.room_key"]
        assert peer.decrypt(first)["content"]["body"] == "First."

    second = await post(server, workspace, ROOM, "Second.")
    assert second["session_id"] == first["session_id"]
    for peer in peers:
        assert peer.read_inbox() == []
        assert peer.decrypt(second)["content"]["body"] == "Second."

    server.members[ROOM] = [BOT, ALICE]
    third = await post(server, workspace, ROOM, "Third.")
    assert third["session_id"] != first["session_id"]
    assert bob.read_inbox() == []
    assert third["session_id"] not in bob.inbound
    for peer in (phone, laptop):
        assert [p["type"] for p in peer.read_inbox()] == ["m.room_key"]
        assert peer.decrypt(third)["content"]["body"] == "Third."


@on_loop
async def test_a_device_that_changes_its_keys_is_not_believed(workspace: Workspace) -> None:
    """Trust on first use: the keys a device id first shows are pinned. A device id that later
    shows other keys is sent no room key, and a room key it sends is not taken."""
    server = E2EHomeserver()
    server.encrypted[ROOM] = ENCRYPTED
    installation = await primed(server, workspace)
    phone = Peer(server, ALICE, "ALICEPHONE")
    await post(server, workspace, ROOM, "Pinned.")
    phone.read_inbox()

    impostor = Peer(server, ALICE, "ALICEPHONE")
    server.members[ROOM] = [BOT, ALICE]
    server.syncs["s1"] = {**batch("s2"), "device_lists": {"changed": [ALICE]}}
    await installation.step()
    await post(server, workspace, ROOM, "After the change.")
    assert impostor.read_inbox() == []

    impostor.share(ROOM)
    forged = impostor.say(ROOM, "$f1", f"{BOT} trust me")
    server.syncs["s2"] = batch("s3", {ROOM: [forged]})
    await installation.step()
    assert workspace.admitted == []


@on_loop
async def test_a_post_into_an_encrypted_room_without_a_store_key_is_refused(
    workspace: Workspace,
) -> None:
    server = E2EHomeserver()
    server.encrypted[ROOM] = ENCRYPTED
    with pytest.raises(SurfaceDeliveryError, match="no device keys"):
        await post(server, workspace, ROOM, "Should not leak.")
    assert server.sent == {}


@on_loop
async def test_the_store_is_unreadable_without_the_slots_key(workspace: Workspace) -> None:
    server = E2EHomeserver()
    server.encrypted[ROOM] = ENCRYPTED
    await primed(server, workspace)
    Peer(server, ALICE, "ALICEPHONE")
    await post(server, workspace, ROOM, "Sealed.")

    async with workspace.engine.begin() as connection:
        rows = (await connection.execute(sa.select(CRYPTO_TABLE))).all()
    assert {row.kind for row in rows} >= {"account", "devices", "olm", "inbound", "outbound"}
    assert {(row.user_id, row.device_id) for row in rows} == {(BOT, BOT_DEVICE)}
    for row in rows:
        assert ROOM not in row.name and ALICE not in row.name
        for secret in (ROOM.encode(), ALICE.encode(), b"pickle", b"session_key", b"Sealed"):
            assert secret not in row.value

    other = CryptoStore(
        workspace, Sealer("another-key-of-at-least-thirty-two-chars"), BOT, BOT_DEVICE
    )
    stolen = CryptoStore(workspace, Sealer(STORE_KEY), BOT, BOT_DEVICE)
    async with stolen.rows() as opened:
        assert await opened.get("account") is not None
    with pytest.raises(StoreLocked):
        async with other.rows() as locked:
            await locked.get("account")

    workspace.credentials[STORE_KEY_SLOT] = "another-key-of-at-least-thirty-two-chars"
    async with MatrixClient(
        workspace.credentials[HOMESERVER_SLOT],
        workspace.credentials[TOKEN_SLOT],
        transport=server.transport,
    ) as client:
        assert await device_for(workspace, client) is None  # type: ignore[arg-type]
    assert server.device_uploads == 1


def test_a_short_store_key_is_refused() -> None:
    with pytest.raises(ValueError, match="shorter"):
        Sealer("short")


def test_a_row_sealed_for_one_address_does_not_open_at_another() -> None:
    sealer = Sealer(STORE_KEY)
    blob = sealer.seal(b"one", {"pickle": "x"})
    assert sealer.open(b"one", blob) == {"pickle": "x"}
    with pytest.raises(StoreLocked):
        sealer.open(b"two", blob)


def test_device_keys_must_be_self_signed() -> None:
    account = vz.Account()
    keys = {
        "user_id": ALICE,
        "device_id": "D",
        "algorithms": [MEGOLM],
        "keys": {
            "curve25519:D": account.curve25519_key.to_base64(),
            "ed25519:D": account.ed25519_key.to_base64(),
        },
    }
    signature = account.sign(crypto.canonical(keys)).to_base64()
    signed = {**keys, "signatures": {ALICE: {"ed25519:D": signature}}}
    assert crypto.verified_device(ALICE, "D", signed) == {
        "curve25519": account.curve25519_key.to_base64(),
        "ed25519": account.ed25519_key.to_base64(),
    }
    assert crypto.verified_device(BOB, "D", signed) is None
    tampered = {
        **signed,
        "keys": {**keys["keys"], "curve25519:D": vz.Account().curve25519_key.to_base64()},
    }
    assert crypto.verified_device(ALICE, "D", tampered) is None
