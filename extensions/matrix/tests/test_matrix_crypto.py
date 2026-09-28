"""End-to-end encryption against a fake homeserver, with real Olm and Megolm on both ends: an
encrypted direct room round trips, a restart keeps its device and its sessions, an event that
arrives before its key is heard once the key lands and never as ciphertext, a post reaches every
member device and no departed one, a device that changes its keys is not believed, a member's client
verifies the bot's device over SAS, and the store opens only under its slot's key."""

import asyncio
import logging
from uuid import uuid4

import pytest

pytest.importorskip("ufo", reason="install ufo from git to run the crypto tests")
pytest.importorskip("vodozemac", reason="install the matrix-e2ee extra to run the crypto tests")
pytest.importorskip("cryptography", reason="install the matrix-e2ee extra to run the crypto tests")

import sqlalchemy as sa  # noqa: E402
import vodozemac as vz  # noqa: E402
from crypto_fakes import (  # noqa: E402
    BOT_DEVICE,
    MEGOLM,
    READY,
    STORE_KEY,
    E2EHomeserver,
    Peer,
    Verifier,
)
from matrix_fakes import ALICE, BOB, BOT, DIRECT, ROOM, Listener, Workspace, batch, on_loop  # noqa: E402
from ufo.sdk.surfaces import (  # noqa: E402
    MidTurnReply,
    SharedArtifact,
    SurfaceDeliveryError,
    TerminalFrame,
    Writeback,
)
from ufo_ext_matrix import crypto  # noqa: E402
from ufo_ext_matrix.client import MatrixClient  # noqa: E402
from ufo_ext_matrix.crypto import STORE_KEY_SLOT, device_for  # noqa: E402
from ufo_ext_matrix.crypto_store import (  # noqa: E402
    CRYPTO_TABLE,
    CryptoStore,
    Rows,
    Sealer,
    StoreLocked,
)
from ufo_ext_matrix.events import txn_id  # noqa: E402
from ufo_ext_matrix.since import read_since  # noqa: E402
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
    assert payload["content"]["msgtype"] == "m.text"
    assert payload["content"]["body"] == "Standup at ten."
    assert payload["content"]["formatted_body"] == "<p>Standup at ten.</p>"


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


async def confirmed(server: E2EHomeserver, workspace: Workspace, user: str) -> dict[str, str]:
    """The devices of `user` the bot holds verified, as the bot's own device answers it."""
    async with MatrixClient(
        workspace.credentials[HOMESERVER_SLOT],
        workspace.credentials[TOKEN_SLOT],
        transport=server.transport,
    ) as client:
        device = await device_for(workspace, client)  # type: ignore[arg-type]
        assert device is not None
        return await device.verified(user)


async def exchange(installation: Installation, verifier: Verifier, rounds: int = 5) -> None:
    """The exchange to its end: one round is one sync of the bot's and the client's answer."""
    for _ in range(rounds):
        await installation.step()
        verifier.answer()


@on_loop
async def test_a_member_verifies_the_bots_device_over_sas(workspace: Workspace) -> None:
    """The member's client starts, and the bot answers every event of the exchange — no command, no
    keyword, nothing but to-device protocol. The client's MAC over the bot's device key is the
    verification the member asked for, and the bot records which device confirmed it."""
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    installation = await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    assert await confirmed(server, workspace, ALICE) == {}

    verifier = Verifier(alice)
    verifier.request()
    await exchange(installation, verifier)

    assert verifier.verified
    assert verifier.done
    assert verifier.cancelled is None
    assert verifier.strings == ["emoji", "decimal"]
    assert await confirmed(server, workspace, ALICE) == {"ALICEPHONE": alice.ed}
    assert workspace.admitted == []


@on_loop
async def test_a_mac_over_a_key_this_device_does_not_hold_ends_in_a_cancel(
    workspace: Workspace,
) -> None:
    """A MAC that covers any key but the pinned one ends the exchange in `m.key_mismatch`, and
    nothing is recorded verified. A false verified is the one outcome worse than none."""
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    installation = await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    verifier = Verifier(alice, honest=False)
    verifier.request()
    await exchange(installation, verifier)

    assert verifier.cancelled == "m.key_mismatch"
    assert not verifier.verified
    assert not verifier.done
    assert await confirmed(server, workspace, ALICE) == {}


@on_loop
async def test_a_member_who_never_verifies_is_served_exactly_as_before(
    workspace: Workspace,
) -> None:
    """Trust on first use is what decides who is sent a room key. A device that never verifies is
    pinned, hears what the bot posts, is heard back, and is recorded verified nowhere."""
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    installation = await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    alice.share(DIRECT)
    server.syncs["s1"] = batch("s2", {DIRECT: [alice.say(DIRECT, "$d1", "what's on today")]})
    await installation.step()
    assert [a["key"] for a in workspace.admitted] == ["$d1"]

    sent = await post(server, workspace, DIRECT, "Standup at ten.")
    assert [p["type"] for p in alice.read_inbox()] == ["m.room_key"]
    assert alice.decrypt(sent)["content"]["body"] == "Standup at ten."
    assert await confirmed(server, workspace, ALICE) == {}


@on_loop
async def test_a_request_in_the_clear_opens_an_exchange_that_runs_over_olm(
    workspace: Workspace,
) -> None:
    """Clients send the opening request with no Olm around it. It names no key and its one effect is
    the `.ready` that comes back, so it is answered — and the exchange it opens finishes as any
    other, every event of it Olm-encrypted."""
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    installation = await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    verifier = Verifier(alice)
    verifier.request(clear=True)
    await installation.step()
    assert verifier.answer() == [READY]
    await exchange(installation, verifier, rounds=4)

    assert verifier.verified and verifier.done
    assert await confirmed(server, workspace, ALICE) == {"ALICEPHONE": alice.ed}


@on_loop
async def test_a_start_in_the_clear_is_refused(
    workspace: Workspace, caplog: pytest.LogCaptureFixture
) -> None:
    """An unencrypted to-device event names a user and not a device, so it can never be the
    evidence that one device is verified. A `.start` in the clear is ended where the member's client
    can show why, rather than left to hang."""
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    installation = await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    verifier = Verifier(alice)
    verifier.begin(clear=True)
    with caplog.at_level(logging.DEBUG):
        await installation.step()
    verifier.answer()

    assert "matrix.verification_in_the_clear" in caplog.text
    assert verifier.cancelled == "m.invalid_message"
    assert not verifier.verified
    assert await confirmed(server, workspace, ALICE) == {}


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


async def pending(workspace: Workspace) -> list[dict]:
    store = CryptoStore(workspace, Sealer(STORE_KEY), BOT, BOT_DEVICE)  # type: ignore[arg-type]
    async with store.rows() as rows:
        return (await rows.get("pending") or {"events": []})["events"]


async def stored_account(workspace: Workspace) -> str:
    """The Curve25519 key of the account the store holds for the bot's device."""
    store = CryptoStore(workspace, Sealer(STORE_KEY), BOT, BOT_DEVICE)  # type: ignore[arg-type]
    async with store.rows() as rows:
        held = await rows.get("account")
    return vz.Account.from_pickle(
        held["pickle"], store.sealer.pickle_key
    ).curve25519_key.to_base64()


@on_loop
async def test_two_processes_opening_one_device_agree_on_one_account(
    workspace: Workspace,
) -> None:
    """`Installation.deliver` and the writeback path each open the device, so two of them meeting a
    first encrypted event together is an ordinary interleaving, not a contrivance. Both leave with
    one account, and the homeserver is offered one set of device keys."""
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    workspace.credentials[STORE_KEY_SLOT] = STORE_KEY
    async with MatrixClient(
        workspace.credentials[HOMESERVER_SLOT],
        workspace.credentials[TOKEN_SLOT],
        transport=server.transport,
    ) as client:
        opened = await asyncio.gather(
            device_for(workspace, client),  # type: ignore[arg-type]
            device_for(workspace, client),  # type: ignore[arg-type]
        )
    keys = {device.identity_key for device in opened if device is not None}
    assert [device is not None for device in opened] == [True, True]
    assert len(keys) == 1
    assert server.device_uploads == 1
    published = server.devices[BOT][BOT_DEVICE]["keys"][f"curve25519:{BOT_DEVICE}"]
    assert published == keys.pop() == await stored_account(workspace)


@on_loop
async def test_a_mint_that_loses_reads_the_winners_account(workspace: Workspace) -> None:
    """The interleaving the primary key arbitrates, held still: a caller whose read saw no account
    mints one, loses the insert, and leaves with the stored account rather than publishing its own
    keys over the winner's. Two accounts for one device id is #16's named failure — the published
    and the stored keys diverge and the bot silently stops decrypting, with no log to say why."""
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    await primed(server, workspace)
    winner = await stored_account(workspace)
    honest = Rows.get
    lied: list[bool] = []

    async def blind(self: Rows, kind: str, *key: str, lock: bool = False) -> object:
        """The stale read: the account row is there and this caller's first look does not see it."""
        if kind == "account" and not lied:
            lied.append(True)
            return None
        return await honest(self, kind, *key, lock=lock)

    Rows.get = blind  # type: ignore[method-assign]
    try:
        async with MatrixClient(
            workspace.credentials[HOMESERVER_SLOT],
            workspace.credentials[TOKEN_SLOT],
            transport=server.transport,
        ) as client:
            late = await device_for(workspace, client)  # type: ignore[arg-type]
    finally:
        Rows.get = honest  # type: ignore[method-assign]

    assert late is not None
    assert late.identity_key == winner
    assert await stored_account(workspace) == winner
    assert server.device_uploads == 1
    assert server.devices[BOT][BOT_DEVICE]["keys"][f"curve25519:{BOT_DEVICE}"] == winner


@on_loop
async def test_a_parked_event_that_will_not_decrypt_is_dropped_rather_than_retried(
    workspace: Workspace,
) -> None:
    """A parked event whose key arrives but whose plaintext is no Matrix event is dropped, named by
    error class, and the stream carries on past it. Raising out of the retry loop would leave the
    position where it was and the pending row unpruned, so one malformed payload would be retried on
    every sync for good and silence that bot."""
    server = E2EHomeserver()
    server.encrypted[ROOM] = ENCRYPTED
    installation = await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    server.syncs["s1"] = batch("s2", {ROOM: [alice.babble(ROOM, "$m1")]})
    assert await installation.step() == 0.0
    assert workspace.admitted == []
    assert await read_since(workspace, BOT) == "s2"  # type: ignore[arg-type]
    assert len(await pending(workspace)) == 1

    alice.forward(ROOM)
    good = alice.say(ROOM, "$m2", f"{BOT} and again")
    server.syncs["s2"] = batch("s3", {ROOM: [good]})
    assert await installation.step() == 0.0
    assert [a["key"] for a in workspace.admitted] == ["$m2"]
    assert await read_since(workspace, BOT) == "s3"  # type: ignore[arg-type]
    assert await pending(workspace) == []


@on_loop
async def test_every_delivery_handler_encrypts_what_it_sends(workspace: Workspace) -> None:
    """A room's words leave by three handlers — the terminal reply, a shared file, and a mid-turn
    reply — and an encrypted room takes ciphertext from all three. A handler that sent its own
    message rather than going through the surface's one seam would put a filename, a subject or a
    mid-turn line on the server's timeline in the clear."""
    server = E2EHomeserver()
    server.encrypted[DIRECT] = ENCRYPTED
    await primed(server, workspace)
    alice = Peer(server, ALICE, "ALICEPHONE")
    surface = MatrixSurface(transport=server.transport, environ={})

    chart = SharedArtifact(
        id=uuid4(),
        blob_key="blob-chart",
        filename="chart.png",
        media_type="image/png",
        size_bytes=4,
        subject="Last week",
        role="file",
    )
    workspace.blob.objects = {chart.blob_key: b"\x89PNG"}
    wb = Writeback(
        turn_id=uuid4(),
        conversation_id=uuid4(),
        agent_id=uuid4(),
        queue_key=DIRECT,
        terminal=TerminalFrame(status="done", text="Standup at ten."),
        artifacts=(chart,),
    )
    reply_ref = await surface.post(workspace, wb)  # type: ignore[arg-type]
    await surface.attach(workspace, wb, str(reply_ref))  # type: ignore[arg-type]
    said = MidTurnReply(
        id=uuid4(),
        turn_id=wb.turn_id,
        conversation_id=wb.conversation_id,
        agent_id=wb.agent_id,
        queue_key=DIRECT,
        message_ref=None,
        text="Halfway through.",
    )
    await surface.speak(workspace, said)  # type: ignore[arg-type]

    assert len(server.sent) == 3
    for event in server.sent.values():
        assert event["type"] == "m.room.encrypted"
        assert event["algorithm"] == MEGOLM
    for leak in ("Standup at ten.", "Halfway through.", "chart.png", "Last week", "mxc://"):
        assert leak not in str(server.sent), leak

    assert [event["type"] for event in alice.read_inbox()] == ["m.room_key"]
    bodies = [alice.decrypt(event)["content"] for event in server.sent.values()]
    said_bodies = [body.get("body", "") for body in bodies]
    for expected in ("Standup at ten.", "Halfway through.", "Last week"):
        assert any(expected in body for body in said_bodies), expected
    [picture] = [body for body in bodies if body["msgtype"] == "m.image"]
    assert picture["filename"] == "chart.png"
    assert picture["url"].startswith("mxc://")


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
