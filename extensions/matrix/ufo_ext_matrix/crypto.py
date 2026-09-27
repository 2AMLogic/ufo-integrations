"""End-to-end encryption for the bot's one device, over vodozemac's Olm and Megolm.

The device is the one the bot's access token is bound to, as `/account/whoami` names it, so a
restart keeps the device its peers already know. Its account and sessions live in the crypto store,
sealed under the `matrix_store_key` slot; with that slot empty the bot has no device keys, hears
nothing in an encrypted room, and refuses to post into one.

Inbound, a `/sync` batch's to-device events are read first — room keys arrive there, Olm-encrypted
to this device — then each `m.room.encrypted` timeline event is decrypted into the plain event it
carries, which the surface reads exactly as it reads an unencrypted one. An event whose session key
has not arrived is parked, its key is asked for, and it is heard once the key lands; past
`PENDING_SECONDS` it is dropped with a warning. Ciphertext is never heard.

Outbound, a message into an encrypted room is Megolm-encrypted, and the session's key is first
shared over Olm with every device of every joined member that has not had it. Devices are trusted on
first use: the keys a device id first shows are pinned, and a device that later shows other keys is
neither sent keys nor believed."""

import base64
import hashlib
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import vodozemac as vz

from ufo.sdk.o11y import log, warn
from ufo.sdk.surfaces import CredentialSlotUnset, SurfaceContext
from ufo_ext_matrix.client import MatrixClient, MatrixError
from ufo_ext_matrix.crypto_store import CryptoStore, Rows, Sealer, StoreLocked
from ufo_ext_matrix.events import ENCRYPTED_TYPE, MESSAGE_TYPE, timeline

STORE_KEY_SLOT = "matrix_store_key"
OLM = "m.olm.v1.curve25519-aes-sha2"
MEGOLM = "m.megolm.v1.aes-sha2"
SIGNED_KEY = "signed_curve25519"
ROOM_KEY = "m.room_key"
FORWARDED_ROOM_KEY = "m.forwarded_room_key"
KEY_REQUEST = "m.room_key_request"
PENDING_SECONDS = 600
PENDING_LIMIT = 200
OLM_SESSIONS_KEPT = 5
ROTATION_MS = 7 * 24 * 3600 * 1000
ROTATION_MSGS = 100

ACCOUNT = "account"
DEVICES = "devices"
OLM_SESSIONS = "olm"
INBOUND = "inbound"
OUTBOUND = "outbound"
PENDING = "pending"


class CryptoUnavailable(Exception):
    """A message is bound for an encrypted room and the bot has no device keys to encrypt it
    with."""


class KeyMissing(Exception):
    """An event's Megolm session has not reached this device."""


def now_ms() -> int:
    return int(time.time() * 1000)


def canonical(value: Any) -> bytes:
    """Matrix canonical JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode().rstrip("=")


def decode(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4))


def verified_device(user_id: str, device_id: str, keys: Any) -> dict[str, str] | None:
    """The Curve25519 and Ed25519 keys a `/keys/query` entry lists, if it is the device it says it
    is and its own Ed25519 key signed it."""
    try:
        if keys["user_id"] != user_id or keys["device_id"] != device_id:
            return None
        curve = keys["keys"][f"curve25519:{device_id}"]
        ed = keys["keys"][f"ed25519:{device_id}"]
        signature = keys["signatures"][user_id][f"ed25519:{device_id}"]
        signed = {k: v for k, v in keys.items() if k not in ("signatures", "unsigned")}
        vz.Ed25519PublicKey.from_base64(ed).verify_signature(
            canonical(signed), vz.Ed25519Signature.from_base64(signature)
        )
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(curve, str):
        return None
    return {"curve25519": curve, "ed25519": ed}


def _verified_key(user_id: str, device_id: str, ed25519: str, key: Any) -> str | None:
    """A claimed one-time key, if the device's Ed25519 key signed it."""
    try:
        signature = key["signatures"][user_id][f"ed25519:{device_id}"]
        signed = {k: v for k, v in key.items() if k not in ("signatures", "unsigned")}
        vz.Ed25519PublicKey.from_base64(ed25519).verify_signature(
            canonical(signed), vz.Ed25519Signature.from_base64(signature)
        )
        value = key["key"]
    except (KeyError, TypeError, ValueError):
        return None
    return value if isinstance(value, str) else None


@dataclass
class Device:
    """The bot's device over one store and one homeserver session."""

    store: CryptoStore
    client: MatrixClient
    account: vz.Account

    @property
    def user_id(self) -> str:
        return self.store.user_id

    @property
    def device_id(self) -> str:
        return self.store.device_id

    @property
    def identity_key(self) -> str:
        return self.account.curve25519_key.to_base64()

    @property
    def signing_key(self) -> str:
        return self.account.ed25519_key.to_base64()

    @property
    def _pickle_key(self) -> bytes:
        return self.store.sealer.pickle_key

    @classmethod
    async def open(cls, store: CryptoStore, client: MatrixClient) -> "Device":
        """The device's account from the store, or a new one — stored, then published — when the
        store holds none for this `(user, device)`."""
        async with store.rows() as rows:
            record = await rows.get(ACCOUNT)
            if record is None:
                account = vz.Account()
                record = {"pickle": account.pickle(store.sealer.pickle_key), "published": False}
                await rows.put(ACCOUNT, value=record)
                log("matrix.crypto_device_new", device_id=store.device_id)
            else:
                account = vz.Account.from_pickle(record["pickle"], store.sealer.pickle_key)
        device = cls(store, client, account)
        if not record["published"]:
            keys = {
                "device_keys": device._device_keys(),
                "one_time_keys": device._one_time_keys(account.max_number_of_one_time_keys // 2),
                "fallback_keys": device._fallback_key(),
            }
            await device._publish(keys)
        return device

    def _signed(self, value: dict[str, Any]) -> dict[str, Any]:
        signature = self.account.sign(canonical(value)).to_base64()
        return {
            **value,
            "signatures": {self.user_id: {f"ed25519:{self.device_id}": signature}},
        }

    def _device_keys(self) -> dict[str, Any]:
        return self._signed(
            {
                "user_id": self.user_id,
                "device_id": self.device_id,
                "algorithms": [OLM, MEGOLM],
                "keys": {
                    f"curve25519:{self.device_id}": self.identity_key,
                    f"ed25519:{self.device_id}": self.signing_key,
                },
            }
        )

    def _one_time_keys(self, count: int) -> dict[str, Any]:
        self.account.generate_one_time_keys(count)
        return {
            f"{SIGNED_KEY}:{key_id}": self._signed({"key": key.to_base64()})
            for key_id, key in self.account.one_time_keys.items()
        }

    def _fallback_key(self) -> dict[str, Any]:
        self.account.generate_fallback_key()
        return {
            f"{SIGNED_KEY}:{key_id}": self._signed({"key": key.to_base64(), "fallback": True})
            for key_id, key in self.account.fallback_key.items()
        }

    async def _publish(self, keys: Mapping[str, Any]) -> None:
        """Upload what the account generated, then record it published. The account is stored
        first, so a failed upload is tried again with the same keys rather than lost."""
        await self._save_account(published=False)
        await self.client.upload_keys(keys)
        self.account.mark_keys_as_published()
        await self._save_account(published=True)

    async def _save_account(self, *, published: bool = True, rows: Rows | None = None) -> None:
        record = {"pickle": self.account.pickle(self._pickle_key), "published": published}
        if rows is not None:
            await rows.put(ACCOUNT, value=record)
            return
        async with self.store.rows() as fresh:
            await fresh.put(ACCOUNT, value=record)

    async def receive(self, batch: Mapping[str, Any]) -> None:
        """Everything a sync batch tells the device: whose devices changed, the to-device events
        addressed to it, and how many one-time keys the homeserver has left to hand out."""
        lists = batch.get("device_lists")
        if isinstance(lists, Mapping):
            changed = [
                u for k in ("changed", "left") for u in lists.get(k) or () if isinstance(u, str)
            ]
            await self._outdate(changed)
        section = batch.get("to_device")
        events = section.get("events", []) if isinstance(section, Mapping) else []
        events = [e for e in events if isinstance(e, Mapping)]
        senders = {e["sender"] for e in events if isinstance(e.get("sender"), str)}
        await self.refresh(senders)
        for event in events:
            try:
                await self._to_device(event)
            except (MatrixError, StoreLocked):
                raise
            except Exception as error:
                warn("matrix.to_device_skipped", error_class=type(error).__name__)
        await self._replenish(
            batch.get("device_one_time_keys_count"),
            batch.get("device_unused_fallback_key_types"),
        )

    async def _replenish(self, counts: Any, fallback_types: Any) -> None:
        keys: dict[str, Any] = {}
        if isinstance(counts, Mapping):
            target = self.account.max_number_of_one_time_keys // 2
            held = counts.get(SIGNED_KEY, 0)
            if isinstance(held, int) and held < target:
                keys["one_time_keys"] = self._one_time_keys(target - held)
        if isinstance(fallback_types, list) and SIGNED_KEY not in fallback_types:
            keys["fallback_keys"] = self._fallback_key()
        if keys:
            await self._publish(keys)

    async def _outdate(self, users: Iterable[str]) -> None:
        async with self.store.rows() as rows:
            for user in users:
                record = await rows.get(DEVICES, user, lock=True)
                if record is not None and not record.get("outdated"):
                    await rows.put(DEVICES, user, value={**record, "outdated": True})

    async def refresh(self, users: Iterable[str]) -> None:
        """Ask the homeserver for the devices of every user whose list the store lacks or knows to
        be outdated, and pin each new device's keys."""
        async with self.store.rows() as rows:
            stale = []
            for user in sorted(set(users)):
                record = await rows.get(DEVICES, user)
                if record is None or record.get("outdated"):
                    stale.append(user)
        if not stale:
            return
        listed = await self.client.query_keys(stale)
        async with self.store.rows() as rows:
            for user in stale:
                record = await rows.get(DEVICES, user, lock=True) or {"pins": {}}
                current = []
                devices = listed.get(user)
                for device_id, keys in (devices if isinstance(devices, Mapping) else {}).items():
                    shown = verified_device(user, device_id, keys)
                    if shown is None:
                        continue
                    pinned = record["pins"].setdefault(device_id, shown)
                    if pinned != shown:
                        warn("matrix.device_keys_changed", device_id=device_id)
                        continue
                    current.append(device_id)
                await rows.put(
                    DEVICES,
                    user,
                    value={"pins": record["pins"], "current": current, "outdated": False},
                )

    async def trusted(self, rows: Rows, users: Iterable[str]) -> dict[tuple[str, str], dict]:
        """The pinned keys of every current device of these users, this device aside."""
        found: dict[tuple[str, str], dict] = {}
        for user in sorted(set(users)):
            record = await rows.get(DEVICES, user)
            if record is None:
                continue
            for device_id in record.get("current", ()):
                if (user, device_id) != (self.user_id, self.device_id):
                    found[(user, device_id)] = record["pins"][device_id]
        return found

    async def _sender_device(self, rows: Rows, user: str, curve: str) -> dict | None:
        for pinned in (await self.trusted(rows, [user])).values():
            if pinned["curve25519"] == curve:
                return pinned
        return None

    async def _to_device(self, event: Mapping[str, Any]) -> None:
        content = event.get("content")
        if event.get("type") != ENCRYPTED_TYPE or not isinstance(content, Mapping):
            return
        if content.get("algorithm") != OLM:
            return
        sender = event.get("sender")
        sender_key = content.get("sender_key")
        ours = (content.get("ciphertext") or {}).get(self.identity_key)
        if not isinstance(sender, str) or not isinstance(sender_key, str) or not ours:
            return
        message = vz.AnyOlmMessage.from_parts(ours["type"], decode(ours["body"]))
        async with self.store.rows() as rows:
            payload = json.loads(await self._olm_decrypt(rows, sender_key, message))
            device = await self._sender_device(rows, sender, sender_key)
            if (
                device is None
                or payload.get("sender") != sender
                or payload.get("recipient") != self.user_id
                or (payload.get("recipient_keys") or {}).get("ed25519") != self.signing_key
                or (payload.get("keys") or {}).get("ed25519") != device["ed25519"]
            ):
                warn("matrix.to_device_untrusted", kind=str(payload.get("type")))
                return
            kind = payload.get("type")
            inner = payload.get("content")
            if kind == ROOM_KEY and isinstance(inner, Mapping):
                await self._room_key(rows, sender, device, inner, forwarded=False)
            elif kind == FORWARDED_ROOM_KEY and isinstance(inner, Mapping):
                if inner.get("sender_key") == sender_key and (
                    inner.get("sender_claimed_ed25519_key") == device["ed25519"]
                ):
                    await self._room_key(rows, sender, device, inner, forwarded=True)

    async def _olm_decrypt(self, rows: Rows, sender_key: str, message: vz.AnyOlmMessage) -> bytes:
        """Decrypt with the sender's session that takes the message, or open an inbound session
        from a pre-key message. The session's new state commits with whatever the plaintext
        carried."""
        record = await rows.get(OLM_SESSIONS, sender_key, lock=True) or {"sessions": []}
        sessions = [vz.Session.from_pickle(p, self._pickle_key) for p in record["sessions"]]
        pre_key = message.to_pre_key()
        for index, session in enumerate(sessions):
            if pre_key is not None and not session.session_matches(pre_key):
                continue
            try:
                plaintext = session.decrypt(message)
            except vz.OlmDecryptionException:
                continue
            sessions.insert(0, sessions.pop(index))
            await self._save_sessions(rows, sender_key, sessions)
            return plaintext
        if pre_key is None:
            raise vz.OlmDecryptionException("no Olm session takes this message")
        session, plaintext = self.account.create_inbound_session(
            vz.Curve25519PublicKey.from_base64(sender_key), pre_key
        )
        await self._save_sessions(rows, sender_key, [session, *sessions])
        await self._save_account(rows=rows)
        return plaintext

    async def _save_sessions(self, rows: Rows, peer: str, sessions: Sequence[vz.Session]) -> None:
        pickles = [s.pickle(self._pickle_key) for s in sessions[:OLM_SESSIONS_KEPT]]
        await rows.put(OLM_SESSIONS, peer, value={"sessions": pickles})

    async def _room_key(
        self, rows: Rows, sender: str, device: dict, content: Mapping[str, Any], *, forwarded: bool
    ) -> None:
        room_id = content.get("room_id")
        session_id = content.get("session_id")
        key = content.get("session_key")
        if content.get("algorithm") != MEGOLM or not all(
            isinstance(v, str) for v in (room_id, session_id, key)
        ):
            return
        if forwarded:
            session = vz.InboundGroupSession.import_session(vz.ExportedSessionKey(key))
        else:
            session = vz.InboundGroupSession(vz.SessionKey(key))
        if session.session_id != session_id:
            warn("matrix.room_key_mismatch")
            return
        held = await rows.get(INBOUND, room_id, session_id, lock=True)
        if held is not None and (
            held["sender"] != sender or held["first_index"] <= session.first_known_index
        ):
            return
        await rows.put(
            INBOUND,
            room_id,
            session_id,
            value={
                "pickle": session.pickle(self._pickle_key),
                "sender": sender,
                "sender_key": device["curve25519"],
                "first_index": session.first_known_index,
            },
        )

    async def decrypt(self, room_id: str, event: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The plain event an `m.room.encrypted` timeline event carries, or None for one that can
        never be read here — another algorithm, a sender other than the session's, a payload
        naming another room. Raises `KeyMissing` while its session has not arrived."""
        content = event.get("content")
        if not isinstance(content, Mapping) or content.get("algorithm") != MEGOLM:
            return None
        session_id = content.get("session_id")
        ciphertext = content.get("ciphertext")
        if not isinstance(session_id, str) or not isinstance(ciphertext, str):
            return None
        async with self.store.rows() as rows:
            held = await rows.get(INBOUND, room_id, session_id)
        if held is None:
            raise KeyMissing(session_id)
        session = vz.InboundGroupSession.from_pickle(held["pickle"], self._pickle_key)
        try:
            decrypted = session.decrypt(vz.MegolmMessage.from_base64(ciphertext))
        except vz.MegolmDecryptionException:
            raise KeyMissing(session_id) from None
        if held["sender"] != event.get("sender"):
            warn("matrix.megolm_sender_mismatch")
            return None
        payload = json.loads(decrypted.plaintext)
        inner = payload.get("content")
        if payload.get("room_id") != room_id or not isinstance(inner, Mapping):
            return None
        inner = dict(inner)
        if "m.relates_to" in content:
            inner["m.relates_to"] = content["m.relates_to"]
        return {**event, "type": payload.get("type"), "content": inner}

    async def park(self, room_id: str, event: Mapping[str, Any]) -> None:
        """Hold an event whose key has not arrived, and ask the sender's devices for it once per
        session."""
        async with self.store.rows() as rows:
            record = await rows.get(PENDING, lock=True) or {"events": []}
            events = record["events"]
            session_id = event.get("content", {}).get("session_id")
            asked = any(
                p["event"].get("content", {}).get("session_id") == session_id for p in events
            )
            if any(p["event"].get("event_id") == event.get("event_id") for p in events):
                return
            events.append({"room_id": room_id, "event": dict(event), "at": now_ms()})
            await rows.put(PENDING, value={"events": events[-PENDING_LIMIT:]})
        if not asked:
            await self._request_key(room_id, event)

    async def _request_key(self, room_id: str, event: Mapping[str, Any]) -> None:
        content = event.get("content", {})
        sender = event.get("sender")
        if not isinstance(sender, str):
            return
        session_id = str(content.get("session_id"))
        request = {
            "action": "request",
            "body": {
                "algorithm": MEGOLM,
                "room_id": room_id,
                "sender_key": content.get("sender_key", ""),
                "session_id": session_id,
            },
            "request_id": hashlib.sha256(f"{room_id}|{session_id}".encode()).hexdigest()[:24],
            "requesting_device_id": self.device_id,
        }
        try:
            await self.client.send_to_device(KEY_REQUEST, uuid4().hex, {sender: {"*": request}})
        except MatrixError as error:
            log("matrix.key_request_failed", status=error.status)

    async def retry(self) -> list[tuple[str, Mapping[str, Any]]]:
        """The parked events whose keys have since arrived, oldest first. An event parked longer
        than `PENDING_SECONDS` is dropped with a warning; the rest stay parked."""
        async with self.store.rows() as rows:
            record = await rows.get(PENDING) or {"events": []}
        if not record["events"]:
            return []
        kept, found = [], []
        deadline = now_ms() - PENDING_SECONDS * 1000
        for parked in record["events"]:
            try:
                plain = await self.decrypt(parked["room_id"], parked["event"])
            except KeyMissing:
                if parked["at"] < deadline:
                    warn("matrix.undecryptable_dropped", waited_seconds=PENDING_SECONDS)
                else:
                    kept.append(parked)
                continue
            if plain is not None:
                found.append((parked["room_id"], plain))
        async with self.store.rows() as rows:
            await rows.put(PENDING, value={"events": kept})
        return found

    async def encrypt(
        self, room_id: str, event_type: str, content: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Megolm-encrypt one event for the room, first sharing the room's session with every
        trusted device of every joined member that lacks it. The session rotates when the room's
        `m.room.encryption` settings say it has served long enough, or when a device it was shared
        with has left, so a departed member cannot read what follows."""
        members = await self.client.joined_members(room_id)
        await self.refresh(members)
        async with self.store.rows() as rows:
            targets = await self.trusted(rows, members)
            record = await rows.get(OUTBOUND, room_id, lock=True)
            session, shared = self._outbound(record, settings, targets)
            if session is None:
                session, shared = vz.GroupSession(), set()
                await self._room_key(
                    rows,
                    self.user_id,
                    {"curve25519": self.identity_key},
                    {
                        "algorithm": MEGOLM,
                        "room_id": room_id,
                        "session_id": session.session_id,
                        "session_key": session.session_key.to_base64(),
                    },
                    forwarded=False,
                )
                record = {"created": now_ms(), "count": 0}
            missing = {d: keys for d, keys in targets.items() if d not in shared}
            if missing:
                room_key = {
                    "algorithm": MEGOLM,
                    "room_id": room_id,
                    "session_id": session.session_id,
                    "session_key": session.session_key.to_base64(),
                }
                shared |= await self._share(rows, missing, room_key)
            ciphertext = session.encrypt(
                canonical({"type": event_type, "content": dict(content), "room_id": room_id})
            )
            await rows.put(
                OUTBOUND,
                room_id,
                value={
                    "pickle": session.pickle(self._pickle_key),
                    "created": record["created"],
                    "count": record["count"] + 1,
                    "shared": sorted(list(d) for d in shared),
                },
            )
        return {
            "algorithm": MEGOLM,
            "sender_key": self.identity_key,
            "ciphertext": ciphertext.to_base64(),
            "session_id": session.session_id,
            "device_id": self.device_id,
        }

    def _outbound(
        self,
        record: Mapping[str, Any] | None,
        settings: Mapping[str, Any],
        targets: Mapping[tuple[str, str], dict],
    ) -> tuple[vz.GroupSession | None, set[tuple[str, str]]]:
        if record is None:
            return None, set()
        shared = {(u, d) for u, d in record["shared"]}
        age_limit = settings.get("rotation_period_ms", ROTATION_MS)
        count_limit = settings.get("rotation_period_msgs", ROTATION_MSGS)
        if (
            record["count"] >= (count_limit if isinstance(count_limit, int) else ROTATION_MSGS)
            or now_ms() - record["created"]
            >= (age_limit if isinstance(age_limit, int) else ROTATION_MS)
            or shared - set(targets)
        ):
            return None, set()
        return vz.GroupSession.from_pickle(record["pickle"], self._pickle_key), shared

    async def _share(
        self, rows: Rows, devices: Mapping[tuple[str, str], dict], room_key: Mapping[str, Any]
    ) -> set[tuple[str, str]]:
        """Send the room key to each device over Olm, opening a session with a claimed one-time key
        where there is none. A device that offers no signed key is left out and tried again on the
        next message."""
        sessions: dict[tuple[str, str], list[vz.Session]] = {}
        unopened = []
        for device, keys in devices.items():
            record = await rows.get(OLM_SESSIONS, keys["curve25519"], lock=True)
            if record and record["sessions"]:
                sessions[device] = [
                    vz.Session.from_pickle(p, self._pickle_key) for p in record["sessions"]
                ]
            else:
                unopened.append(device)
        if unopened:
            wanted: dict[str, list[str]] = {}
            for user, device_id in unopened:
                wanted.setdefault(user, []).append(device_id)
            claimed = await self.client.claim_keys(wanted)
            for user, device_id in unopened:
                pinned = devices[(user, device_id)]
                offered = (claimed.get(user) or {}).get(device_id) or {}
                key = next(
                    (
                        _verified_key(user, device_id, pinned["ed25519"], value)
                        for key_id, value in offered.items()
                        if key_id.startswith(f"{SIGNED_KEY}:")
                    ),
                    None,
                )
                if key is None:
                    log("matrix.no_one_time_key", device_id=device_id)
                    continue
                sessions[(user, device_id)] = [
                    self.account.create_outbound_session(
                        vz.Curve25519PublicKey.from_base64(pinned["curve25519"]),
                        vz.Curve25519PublicKey.from_base64(key),
                    )
                ]
        messages: dict[str, dict[str, Any]] = {}
        for (user, device_id), held in sessions.items():
            pinned = devices[(user, device_id)]
            payload = {
                "type": ROOM_KEY,
                "content": dict(room_key),
                "sender": self.user_id,
                "sender_device": self.device_id,
                "keys": {"ed25519": self.signing_key},
                "recipient": user,
                "recipient_keys": {"ed25519": pinned["ed25519"]},
            }
            kind, body = held[0].encrypt(canonical(payload)).to_parts()
            messages.setdefault(user, {})[device_id] = {
                "algorithm": OLM,
                "sender_key": self.identity_key,
                "ciphertext": {pinned["curve25519"]: {"type": kind, "body": encode(body)}},
            }
            await self._save_sessions(rows, pinned["curve25519"], held)
        if messages:
            await self.client.send_to_device(ENCRYPTED_TYPE, uuid4().hex, messages)
        return set(sessions)


async def device_for(ctx: SurfaceContext, client: MatrixClient) -> Device | None:
    """The bot's device for this workspace, or None where it has none: an empty store-key slot, a
    token bound to no device, a slot holding a key the store was not sealed with, or a homeserver
    that refuses the device's keys."""
    try:
        secret = await ctx.credential(STORE_KEY_SLOT)
    except CredentialSlotUnset:
        return None
    user_id, device_id = await client.identity()
    if device_id is None:
        warn("matrix.crypto_no_device")
        return None
    try:
        store = CryptoStore(ctx, Sealer(secret), user_id, device_id)
        return await Device.open(store, client)
    except ValueError:
        warn("matrix.crypto_store_key_short")
    except StoreLocked:
        warn("matrix.crypto_store_locked", device_id=device_id)
    except MatrixError as error:
        if error.status == 429 or error.status >= 500 or error.unauthorized:
            raise
        warn("matrix.crypto_keys_refused", status=error.status, errcode=error.errcode)
    return None


async def inbound(
    device: Device | None,
    batch: Mapping[str, Any],
    earlier: Mapping[str, Sequence[Mapping[str, Any]]],
    admitting: bool,
) -> list[tuple[str, Mapping[str, Any]]]:
    """The batch's timeline as the surface hears it: encrypted events replaced by the plain events
    they carry, parked events whose keys have arrived ahead of them, and nothing still ciphertext.
    Without a device the timeline is heard as it came, and an encrypted event founds nothing."""
    events = list(timeline(batch, earlier))
    if device is None:
        return events
    await device.receive(batch)
    heard = await device.retry()
    for room_id, event in events:
        if event.get("type") != ENCRYPTED_TYPE:
            heard.append((room_id, event))
            continue
        try:
            plain = await device.decrypt(room_id, event)
        except KeyMissing:
            if admitting:
                await device.park(room_id, event)
            continue
        except (ValueError, KeyError, TypeError) as error:
            warn("matrix.undecryptable", error_class=type(error).__name__)
            continue
        if plain is not None:
            heard.append((room_id, plain))
    return heard


async def outbound(
    ctx: SurfaceContext, client: MatrixClient, room_id: str, content: Mapping[str, Any]
) -> tuple[str, Mapping[str, Any]]:
    """The event type and content a message goes out as: itself in a plain room, Megolm
    ciphertext in an encrypted one."""
    settings = await client.encryption(room_id)
    if settings is None:
        return MESSAGE_TYPE, content
    if settings.get("algorithm") != MEGOLM:
        raise CryptoUnavailable(f"the room is encrypted with {settings.get('algorithm')}")
    device = await device_for(ctx, client)
    if device is None:
        raise CryptoUnavailable("the room is encrypted and the bot has no device keys")
    return ENCRYPTED_TYPE, await device.encrypt(room_id, MESSAGE_TYPE, content, settings)
