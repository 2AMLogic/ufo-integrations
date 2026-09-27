"""What a `/sync` batch says, read without the runtime: which events are a member's words, which
rooms invite the bot, and the identifiers the surface derives from them.

Nothing here imports `ufo` or an HTTP client, so the contract tests hold these rules on a checkout
with neither installed. A message founds a turn only if it passes `room_message`; everything the
surface does with it after that is `surface.py`'s."""

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

SURFACE = "matrix"
MESSAGE_TYPE = "m.room.message"
TEXT_MSGTYPE = "m.text"
REPLACE_RELATION = "m.replace"
ROOM_KEY_CHARS = 32
SYNC_TIMELINE_LIMIT = 50
SYNC_FILTER = json.dumps(
    {
        "presence": {"types": []},
        "account_data": {"types": []},
        "room": {
            "timeline": {"limit": SYNC_TIMELINE_LIMIT},
            "ephemeral": {"types": []},
            "account_data": {"types": []},
            "state": {"lazy_load_members": True},
        },
    },
    separators=(",", ":"),
)


@dataclass(frozen=True)
class RoomMessage:
    """One plain-text message a member sent into a room: the only event shape that may found a
    turn. `mentions` is the MXIDs the sender's client says it addressed."""

    room_id: str
    event_id: str
    sender: str
    body: str
    formatted_body: str
    mentions: frozenset[str]

    def addresses(self, bot: str) -> bool:
        """Whether the sender named the bot: an intentional mention, or a pill a client without
        intentional mentions rendered into the message."""
        return bot in self.mentions or bot in self.body or bot in self.formatted_body


def server_name(mxid: str) -> str:
    """The homeserver half of a user or room id — everything after the first colon."""
    _, separator, server = mxid.partition(":")
    if not separator or not server:
        raise ValueError(f"not a Matrix identifier: {mxid!r}")
    return server


def localpart(mxid: str) -> str:
    return mxid.partition(":")[0].removeprefix("@")


def room_key(room_id: str) -> str:
    """The colon-free name a room audience carries. A room id is `!opaque:server`, and an audience
    component may not hold a colon, so the room is named by a digest of its id instead."""
    return hashlib.sha256(room_id.encode()).hexdigest()[:ROOM_KEY_CHARS]


def txn_id(turn_id: UUID) -> str:
    """The transaction id a reply is sent under. One turn has one terminal reply, so a retried post
    for the same turn reaches the homeserver as the same transaction and lands once."""
    return f"ufo-{turn_id}"


def permalink(room_id: str, event_id: str) -> str:
    return f"https://matrix.to/#/{quote(room_id, safe='!:')}/{quote(event_id, safe='$:')}"


def room_message(room_id: str, event: Mapping[str, Any]) -> RoomMessage | None:
    """The event as a member's words, or None when it can found no turn: any type but
    `m.room.message` (an encrypted event is `m.room.encrypted`, a redaction `m.room.redaction`), a
    msgtype other than `m.text` (a bot's `m.notice` among them), an edit, a redacted message, or one
    with no text."""
    if event.get("type") != MESSAGE_TYPE or event.get("state_key") is not None:
        return None
    unsigned = event.get("unsigned")
    if isinstance(unsigned, Mapping) and "redacted_because" in unsigned:
        return None
    content = event.get("content")
    if not isinstance(content, Mapping) or content.get("msgtype") != TEXT_MSGTYPE:
        return None
    relates = content.get("m.relates_to")
    if isinstance(relates, Mapping) and relates.get("rel_type") == REPLACE_RELATION:
        return None
    if "m.new_content" in content:
        return None
    body = content.get("body")
    event_id = event.get("event_id")
    sender = event.get("sender")
    if not isinstance(body, str) or not body.strip():
        return None
    if not isinstance(event_id, str) or not isinstance(sender, str):
        return None
    formatted = content.get("formatted_body")
    return RoomMessage(
        room_id=room_id,
        event_id=event_id,
        sender=sender,
        body=body,
        formatted_body=formatted if isinstance(formatted, str) else "",
        mentions=_mentions(content),
    )


def _mentions(content: Mapping[str, Any]) -> frozenset[str]:
    mentions = content.get("m.mentions")
    if not isinstance(mentions, Mapping):
        return frozenset()
    users = mentions.get("user_ids")
    if not isinstance(users, list):
        return frozenset()
    return frozenset(user for user in users if isinstance(user, str))


def timeline(batch: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Every timeline event of every joined room, in the order the homeserver sent them."""
    for room_id, room in _joined(batch).items():
        events = room.get("timeline", {}).get("events", [])
        for event in events:
            if isinstance(event, Mapping):
                yield room_id, event


def room_names(batch: Mapping[str, Any]) -> dict[str, str]:
    """The name each room carries as of this batch, where the batch names one."""
    names: dict[str, str] = {}
    for room_id, room in _joined(batch).items():
        for section in ("state", "timeline"):
            for event in room.get(section, {}).get("events", []):
                if not isinstance(event, Mapping) or event.get("type") != "m.room.name":
                    continue
                name = event.get("content", {}).get("name")
                if isinstance(name, str) and name.strip():
                    names[room_id] = name.strip()
    return names


def invites(batch: Mapping[str, Any], bot: str) -> Iterator[tuple[str, str]]:
    """Each room the bot is invited to in this batch, with the MXID that invited it."""
    rooms = batch.get("rooms", {}).get("invite", {})
    if not isinstance(rooms, Mapping):
        return
    for room_id, room in rooms.items():
        for event in room.get("invite_state", {}).get("events", []):
            if (
                isinstance(event, Mapping)
                and event.get("type") == "m.room.member"
                and event.get("state_key") == bot
                and event.get("content", {}).get("membership") == "invite"
                and isinstance(event.get("sender"), str)
            ):
                yield room_id, event["sender"]
                break


def next_batch(batch: Mapping[str, Any]) -> str:
    token = batch.get("next_batch")
    if not isinstance(token, str) or not token:
        raise ValueError("sync response carries no next_batch")
    return token


def _joined(batch: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    joined = batch.get("rooms", {}).get("join", {})
    return joined if isinstance(joined, Mapping) else {}
