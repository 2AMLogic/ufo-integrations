"""A fake homeserver behind an httpx `MockTransport`, and fakes of the two surface contexts that
record what the surface asked core to do. The extension's own tables are real: a surface context's
`transaction` yields an in-memory SQLite connection holding them, so where a turn stands, which
message it answers, and what a member proved are read back the way a deploy reads them. So is the
audience rule: `conversation_for` narrows through core's own `narrow_audience`, and raises where
core raises."""

import asyncio
import functools
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ufo.runtime.turns.audience import (
    SHARED_AUDIENCE,
    audience_member,
    narrow_audience,
    parse_audience,
)
from ufo.sdk.audience import Audience
from ufo.sdk.surfaces import Admitted, AmbientMessage, CredentialSlotUnset, SharedArtifact
from ufo_ext_matrix.answering import ANSWERING_TABLE
from ufo_ext_matrix.client import MEDIA_PATH
from ufo_ext_matrix.linking import CLAIM_TABLE, LINK_TABLE
from ufo_ext_matrix.since import SINCE_TABLE
from ufo_ext_matrix.surface import HOMESERVER_SLOT, TOKEN_SLOT

BOT = "@ufo:example.org"
HOMESERVER = "https://matrix.example.org"
TOKEN = "syt_secret_bot_token_value"
ROOM = "!ops:example.org"
DIRECT = "!direct:example.org"
ALICE = "@alice:example.org"
BOB = "@bob:example.org"
OUTSIDER = "@carol:elsewhere.test"
STRANGER = "@mallory:example.org"


def text(event_id: str, sender: str, body: str, **content: object) -> dict[str, Any]:
    return {
        "type": "m.room.message",
        "event_id": event_id,
        "sender": sender,
        "content": {"msgtype": "m.text", "body": body, **content},
    }


def mention(event_id: str, sender: str, body: str) -> dict[str, Any]:
    return text(event_id, sender, body, **{"m.mentions": {"user_ids": [BOT]}})


def batch(token: str, rooms: Mapping[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    return {
        "next_batch": token,
        "rooms": {
            "join": {
                room: {"timeline": {"events": events}} for room, events in (rooms or {}).items()
            }
        },
    }


@dataclass
class Homeserver:
    """Serves `/sync` from a script keyed by the `since` it is asked for, the room member lists,
    and idempotent sends. Every request is recorded, headers included, so a test reads exactly what
    went over the wire."""

    syncs: dict[str | None, dict[str, Any]] = field(default_factory=dict)
    members: dict[str, list[str]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    sent: dict[str, dict[str, Any]] = field(default_factory=dict)
    joined: list[str] = field(default_factory=list)
    failure: httpx.Response | None = None
    forbidden: set[str] = field(default_factory=set)
    history: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    uploaded: list[tuple[str, bytes]] = field(default_factory=list)
    refused_uploads: set[str] = field(default_factory=set)
    limited_uploads: set[str] = field(default_factory=set)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"errcode": "M_UNKNOWN_TOKEN"})
        if self.failure is not None:
            return self.failure
        if request.url.path == f"{MEDIA_PATH}/upload":
            return self.uploaded_media(request)
        path = request.url.path.removeprefix("/_matrix/client/v3")
        match request.method, path.split("/")[1:]:
            case "GET", ["sync"]:
                since = request.url.params.get("since")
                return httpx.Response(200, json=self.syncs.get(since, batch(since or "s0")))
            case "GET", ["account", "whoami"]:
                return httpx.Response(200, json={"user_id": BOT})
            case ("GET", ["rooms", room, "joined_members"]) | ("POST", ["join", room]) if (
                room in self.forbidden
            ):
                return httpx.Response(403, json={"errcode": "M_FORBIDDEN"})
            case "GET", ["rooms", room, "joined_members"]:
                return httpx.Response(
                    200, json={"joined": {m: {} for m in self.members.get(room, [])}}
                )
            case "GET", ["rooms", room, "messages"]:
                start = request.url.params.get("from", "")
                return httpx.Response(200, json=self.history.get((room, start), {"chunk": []}))
            case "PUT", ["rooms", room, "send", "m.room.message", txn]:
                if txn not in self.sent:
                    self.sent[txn] = {
                        "room": room,
                        "event_id": f"$sent{len(self.sent)}",
                        **json.loads(request.content),
                    }
                return httpx.Response(200, json={"event_id": self.sent[txn]["event_id"]})
            case "POST", ["join", room]:
                self.joined.append(room)
                return httpx.Response(200, json={"room_id": room})
        return httpx.Response(404, json={"errcode": "M_UNRECOGNIZED"})

    def uploaded_media(self, request: httpx.Request) -> httpx.Response:
        filename = request.url.params.get("filename", "")
        if filename in self.refused_uploads:
            return httpx.Response(413, json={"errcode": "M_TOO_LARGE"})
        if filename in self.limited_uploads:
            return httpx.Response(429, json={"errcode": "M_LIMIT_EXCEEDED", "retry_after_ms": 1500})
        self.uploaded.append((filename, request.content))
        return httpx.Response(200, json={"content_uri": f"mxc://example.org/{filename}"})

    def sent_under(self, prefix: str) -> list[dict[str, Any]]:
        """Every message sent under a transaction id starting `prefix`, in the order it was sent."""
        return [sent for txn, sent in self.sent.items() if txn.startswith(prefix)]

    def since_asked(self) -> list[str | None]:
        return [r.url.params.get("since") for r in self.requests if r.url.path.endswith("/sync")]


async def extension_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("workspace", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    for table in (SINCE_TABLE, ANSWERING_TABLE, CLAIM_TABLE, LINK_TABLE):
        table.to_metadata(metadata)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    return engine


@dataclass
class Blob:
    """The workspace's blob store as `attach` reads it. A key the store does not hold raises, the
    way a file whose bytes went missing does."""

    objects: dict[str, bytes] = field(default_factory=dict)

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]


@dataclass
class Workspace:
    """A surface context's reach into core, recorded. `wanted` is the ambient decision's answer;
    `broken` names the event ids whose admission raises, and `lost` maps an event id to the
    database failure its admission raises. Alice and Bob are members."""

    engine: AsyncEngine
    workspace_id: UUID = field(default_factory=uuid4)
    credentials: dict[str, str] = field(
        default_factory=lambda: {HOMESERVER_SLOT: HOMESERVER, TOKEN_SLOT: TOKEN}
    )
    domain: str | None = "example.org"
    members: dict[str, UUID] = field(
        default_factory=lambda: {"alice@example.org": uuid4(), "bob@example.org": uuid4()}
    )
    linked: dict[str, UUID] = field(default_factory=dict)
    conversations: dict[str, tuple[UUID, str]] = field(default_factory=dict)
    wanted: bool = True
    asked: list[tuple[AmbientMessage, tuple[AmbientMessage, ...]]] = field(default_factory=list)
    admitted: list[dict[str, Any]] = field(default_factory=list)
    broken: set[str] = field(default_factory=set)
    lost: dict[str, BaseException] = field(default_factory=dict)
    blob: Blob = field(default_factory=Blob)
    portal: bool = True

    async def credential(self, slot: str) -> str:
        if slot not in self.credentials:
            raise CredentialSlotUnset(slot)
        return self.credentials[slot]

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        async with self.engine.begin() as connection:
            yield connection

    def home_url(self, fragment: str = "") -> str | None:
        return f"https://ufo.example.org/surface/web{fragment}"

    async def report_url(self, conversation_id: UUID, artifact: SharedArtifact) -> str | None:
        """The portal link core's rule allows: a deploy without a portal offers none, and a room
        the portal shows nobody — anything but the shared audience or a member's own — offers none
        either, exactly the gate `SurfaceContext.report_url` applies."""
        if not self.portal:
            return None
        audience = next(
            (audience for held, audience in self.conversations.values() if held == conversation_id),
            None,
        )
        if audience is None:
            return None
        parsed = parse_audience(audience)
        if parsed != SHARED_AUDIENCE and audience_member(parsed) is None:
            return None
        return self.home_url(f"#/c/{conversation_id}?report={artifact.id}")

    async def linked_member(self, external_id: str) -> UUID | None:
        return self.linked.get(external_id)

    async def workspace_domain(self) -> str | None:
        return self.domain

    async def link_member(self, external_id: str, email: str) -> UUID | None:
        member = self.members.get(email)
        if member is not None:
            self.linked[external_id] = member
        return member

    async def link_member_id(self, external_id: str, member_id: UUID) -> UUID | None:
        if member_id not in self.members.values():
            return None
        self.linked.setdefault(external_id, member_id)
        return member_id

    async def find_conversation(self, queue_key: str) -> UUID | None:
        found = self.conversations.get(queue_key)
        return None if found is None else found[0]

    async def conversation_for(self, queue_key: str, audience: Audience, **kwargs: object) -> UUID:
        found = self.conversations.get(queue_key)
        if found is None:
            self.conversations[queue_key] = (uuid4(), audience)
        else:
            self.conversations[queue_key] = (found[0], narrow_audience(found[1], audience))
        return self.conversations[queue_key][0]

    async def ambient_reply_wanted(
        self, message: AmbientMessage, history: tuple[AmbientMessage, ...]
    ) -> bool:
        self.asked.append((message, history))
        return self.wanted

    async def admit(
        self,
        conversation_id: UUID,
        body: str,
        idempotency_key: str | None = None,
        context: object = None,
        *,
        speaker_member_id: UUID | None,
    ) -> Admitted:
        if idempotency_key in self.broken:
            raise ValueError("admission refused this event")
        if idempotency_key in self.lost:
            raise self.lost[idempotency_key]
        for prior in self.admitted:
            if prior["key"] == idempotency_key:
                return Admitted(turn_id=prior["turn_id"], opened_run=False)
        turn_id = uuid4()
        self.admitted.append(
            {
                "key": idempotency_key,
                "turn_id": turn_id,
                "conversation_id": conversation_id,
                "body": body,
                "context": context,
                "speaker": speaker_member_id,
            }
        )
        return Admitted(turn_id=turn_id, opened_run=True)


@dataclass
class Listener:
    """The fleet gate: binds the bot's workspace when the bot is bound, and nothing otherwise."""

    workspace_ctx: Workspace
    bound: frozenset[str] = frozenset({BOT})
    surface: str = "matrix"
    owned: bool = True

    @asynccontextmanager
    async def workspace(self, installation_id: str) -> AsyncIterator[Workspace | None]:
        if not self.owned:
            raise RuntimeError("surface listener 'matrix' lost fleet ownership")
        yield self.workspace_ctx if installation_id in self.bound else None


def on_loop(test: Callable[..., Awaitable[None]]) -> Callable[..., None]:
    """Run an async test on its own loop with a fresh `Workspace` passed as `workspace`, so the
    suite needs no async pytest plugin and every engine lives and dies on the loop that made it."""
    params = [p for p in inspect.signature(test).parameters.values() if p.name != "workspace"]

    @functools.wraps(test)
    def run(*args: object, **kwargs: object) -> None:
        async def scenario() -> None:
            engine = await extension_engine()
            try:
                await test(*args, workspace=Workspace(engine=engine), **kwargs)
            finally:
                await engine.dispose()

        asyncio.run(scenario())

    run.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    return run
