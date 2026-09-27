"""The Matrix surface: a bot user's `/sync` stream in, one room message out per terminal turn.

A room is a conversation, keyed by its room id; its speakers are members where one resolves. The
surface is durable and installation-routed — the installation id is the bot's MXID, bound to one
workspace — so ingress is the listener alone and no request is routed to it.

Most lines in a room are not addressed to the agent. A message from a member founds a turn when it
mentions the bot, when it is sent in a direct room (the bot and one other), or when the room already
holds a conversation and `ambient_reply_wanted` says the agent is wanted; anything else is heard,
kept as evidence for the next decision, and admits nothing. A sender who resolves to no member
founds nothing, however it addresses the bot."""

import asyncio
import math
import os
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict

from ufo.sdk.audience import (
    Audience,
    foreign_room_audience,
    room_audience,
)
from ufo.sdk.http import Request
from ufo.sdk.o11y import log, warn
from ufo.sdk.surfaces import (
    AMBIENT_CONTEXT_ELEMENT,
    AMBIENT_HISTORY_MESSAGES,
    NOTHING_DELIVERED,
    AmbientMessage,
    CredentialSlotUnset,
    NothingDelivered,
    SurfaceAuth,
    SurfaceContext,
    SurfaceDeliveryError,
    SurfaceInstallationConflict,
    SurfaceListenerContext,
    TurnContext,
    Writeback,
    fence_member_message,
    is_silence_sentinel,
    mint_marker,
    writeback_says_nothing,
)
from ufo.sdk.tools import TextContent, ToolContext, ToolResult
from ufo_ext_matrix.client import MatrixClient, MatrixError
from ufo_ext_matrix.events import (
    SURFACE,
    RoomMessage,
    gaps,
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
from ufo_ext_matrix.since import read_since, write_since

BOTS_ENV = "UFO_MATRIX_BOTS"
HOMESERVER_SLOT = "matrix_homeserver"
TOKEN_SLOT = "matrix_access_token"
IDLE_SECONDS = 30.0
BACKOFF_SECONDS = (1.0, 2.0, 5.0, 15.0, 30.0, 60.0)
AMBIENT_CONTEXT_LINES = 10
ROSTER_LIMIT = 50
BACKFILL_PAGES = 5

FAILED_LINE = "This turn failed before it could answer."
CANCELLED_LINE = "This turn was stopped."
ELSEWHERE_LINE = "The next step happens in the workspace"
FILES_LINE = "This turn shared files, which are in the workspace"


class FleetOwnershipLost(RuntimeError):
    """The fleet no longer owns this listener: the runner's to act on, so it ends the stream."""


class ConnectInput(BaseModel):
    """Nothing: the bot is whoever the workspace's access token belongs to. An action bound to an
    object takes exactly the fields it declares, so a call naming a bot of its own is refused."""

    model_config = ConfigDict(extra="forbid")


def installations(configured: str) -> tuple[str, ...]:
    """The bot MXIDs a deploy names, comma- or space-separated, in order and once each."""
    named = configured.replace(",", " ").split()
    return tuple(dict.fromkeys(named))


def reply_text(writeback: Writeback, workspace_url: str | None) -> str:
    """The one message a terminal turn becomes. A failed turn says so in the surface's own words; a
    cancelled turn posts the reason core gave — an archived conversation, a revoked seat — or, with
    none, says it was stopped; a question is written out with its options, since a room has no
    buttons; and what a room cannot carry — a connect or credential handoff, a shared file — points
    at the workspace."""
    terminal = writeback.terminal
    text = terminal.text.strip()
    if terminal.status == "failed":
        return FAILED_LINE
    if terminal.status == "cancelled":
        return text if text and not is_silence_sentinel(text) else CANCELLED_LINE
    parts: list[str] = []
    if text and not is_silence_sentinel(text):
        parts.append(text)
    if terminal.question is not None:
        for asked in terminal.question.questions:
            options = asked.options or ()
            lines = [asked.question, *(f"{n}. {o.label}" for n, o in enumerate(options, 1))]
            parts.append("\n".join(lines))
    where = f": {workspace_url}" if workspace_url else "."
    if terminal.connect_request is not None or terminal.credential_request is not None:
        parts.append(ELSEWHERE_LINE + where)
    if writeback.artifacts:
        parts.append(FILES_LINE + where)
    return "\n\n".join(parts)


@dataclass
class Heard:
    """One room line as the ambient decision reads it, and whether it already founded a turn — a
    line the transcript holds is not repeated in the next turn's room context."""

    line: AmbientMessage
    admitted: bool = False


def room_context(marker: str, heard: Sequence[Heard]) -> str:
    """The room lines the agent did not take part in, newest last, as the ambient element one
    admitted message carries ahead of its own words."""
    lines = [
        f"{h.line.speaker}: {h.line.text}" for h in heard if not h.line.own and not h.admitted
    ][-AMBIENT_CONTEXT_LINES:]
    if not lines:
        return ""
    element = f"{AMBIENT_CONTEXT_ELEMENT}_{marker}"
    return f"<{element}>\n" + "\n".join(lines) + f"\n</{element}>\n"


def audience_for(room_id: str, internal: bool) -> Audience:
    """Who a room's conversation may disclose to: the room, and workspace-shared memory with it, when
    everyone in it is a member; otherwise the room alone, sealed foreign. A direct room is a room
    like any other, so a room's audience only ever narrows — room to foreign when a non-member
    joins, and foreign for good after that."""
    key = room_key(room_id)
    return room_audience(SURFACE, key) if internal else foreign_room_audience(SURFACE, key)


def _refused(error: MatrixError) -> bool:
    """A refusal no retry changes — the bot was removed from the room, the invite was withdrawn.
    The batch goes on without that room rather than stalling the stream behind it; a rate limit or
    a server error raises, and the batch is read again."""
    return 400 <= error.status < 500 and error.status != 429 and not error.unauthorized


def _server(mxid: str) -> str | None:
    try:
        return server_name(mxid)
    except ValueError:
        return None


@dataclass
class Roster:
    """Who in one batch resolves to a member, each MXID asked once. A linked MXID is its member; on
    first contact an MXID on the workspace's own domain links to the member whose email is
    `localpart@domain` — the homeserver serving that domain vouches for its users as the mail
    server does for addresses. Any other MXID is nobody."""

    ctx: SurfaceContext
    known: dict[str, UUID | None] = field(default_factory=dict)
    _domain: list[str | None] = field(default_factory=list)

    async def domain(self) -> str | None:
        if not self._domain:
            self._domain.append(await self.ctx.workspace_domain())
        return self._domain[0]

    async def member(self, mxid: str) -> UUID | None:
        if mxid not in self.known:
            self.known[mxid] = await self._resolve(mxid)
        return self.known[mxid]

    async def internal(self, bot: str, joined: frozenset[str]) -> bool:
        """Whether everyone joined but the bot is a member. A workspace with no domain of its own,
        and a room past `ROSTER_LIMIT`, are foreign without asking."""
        others = sorted(joined - {bot})
        if len(others) > ROSTER_LIMIT or await self.domain() is None:
            return False
        for mxid in others:
            if await self.member(mxid) is None:
                return False
        return True

    async def _resolve(self, mxid: str) -> UUID | None:
        linked = await self.ctx.linked_member(mxid)
        if linked is not None:
            return linked
        domain = await self.domain()
        if domain is None or _server(mxid) != domain:
            return None
        return await self.ctx.link_member(mxid, f"{localpart(mxid)}@{domain}")


async def refuse_requests(_request: Request, _auth: SurfaceAuth) -> None:
    """Matrix reaches this surface through its listener; no inbound request names a workspace."""
    return None


@dataclass
class MatrixSurface:
    """The surface's handlers over one HTTP transport. A deploy uses the default instance; a test
    builds one over a fake homeserver."""

    transport: httpx.AsyncBaseTransport | None = None
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

    def client(self, homeserver: str, access_token: str) -> MatrixClient:
        return MatrixClient(homeserver, access_token, transport=self.transport)

    async def listen(self, listener: SurfaceListenerContext) -> None:
        bots = installations(self.environ.get(BOTS_ENV, ""))
        if not bots:
            log("matrix.no_installations", env=BOTS_ENV)
            await asyncio.Event().wait()
        await asyncio.gather(*(Installation(self, listener, bot).run() for bot in bots))

    async def post(self, ctx: SurfaceContext, writeback: Writeback) -> str | NothingDelivered:
        if writeback_says_nothing(writeback):
            return NOTHING_DELIVERED
        body = reply_text(writeback, ctx.home_url())
        try:
            homeserver = await ctx.credential(HOMESERVER_SLOT)
            token = await ctx.credential(TOKEN_SLOT)
        except CredentialSlotUnset as unset:
            raise SurfaceDeliveryError(f"matrix slot {unset.args[0]} is empty") from None
        try:
            async with self.client(homeserver, token) as client:
                return await client.send_text(writeback.queue_key, txn_id(writeback.turn_id), body)
        except MatrixError as error:
            retry = error.retry_after_ms
            raise SurfaceDeliveryError(
                str(error), retry_after_seconds=None if retry is None else math.ceil(retry / 1000)
            ) from None
        except httpx.HTTPError as error:
            raise SurfaceDeliveryError(f"send failed: {type(error).__name__}") from None

    async def connect(self, ctx: ToolContext, _args: ConnectInput) -> ToolResult:
        """Bind the workspace's bot to this workspace: ask the homeserver whose token the slot
        holds, and make that MXID the installation the listener routes by."""
        ext = ctx.ext
        if ext is None:
            raise RuntimeError("matrix_connect dispatched without its ExtensionContext")
        try:
            homeserver = await ext.credentials.get(HOMESERVER_SLOT)
            token = await ext.credentials.get(TOKEN_SLOT)
        except CredentialSlotUnset as unset:
            return _said(f"The {unset.args[0]} credential is empty. Fill it, then connect again.")
        try:
            async with self.client(homeserver, token) as client:
                bot = await client.whoami()
        except MatrixError as error:
            return _said(f"The homeserver refused the bot's token: {error}.", error=True)
        except httpx.HTTPError as error:
            return _said(f"The homeserver did not answer: {type(error).__name__}.", error=True)
        try:
            await ext.installations.bind(SURFACE, bot)
        except SurfaceInstallationConflict:
            return _said(f"{bot} is already connected to another workspace.", error=True)
        listed = bot in installations(self.environ.get(BOTS_ENV, ""))
        tail = (
            "It is listening." if listed else f"It listens once the deploy's {BOTS_ENV} names it."
        )
        return _said(f"Connected {bot}. {tail}")


def _said(text: str, *, error: bool = False) -> ToolResult:
    return ToolResult(content=(TextContent(text=text),), is_error=error)


@dataclass
class Installation:
    """One bot's stream: sync, deliver, record where it stands, repeat. What it has heard in each
    room lives in the process and is evidence only — the durable facts are the stored `since` and
    the turns admission recorded under each event id."""

    surface: MatrixSurface
    listener: SurfaceListenerContext
    bot: str
    heard: dict[str, deque[Heard]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)

    async def run(self) -> None:
        """Sync until cancelled. A failure backs this bot off and leaves every other bot running;
        only `FleetOwnershipLost` ends the stream, since that is the runner's to act on."""
        failures = 0
        while True:
            try:
                wait = await self.step()
                failures = 0
            except FleetOwnershipLost:
                raise
            except Exception as error:
                wait = self._backoff(error, failures)
                failures += 1
                warn(
                    "matrix.sync_failed",
                    installation=self.bot,
                    error_class=type(error).__name__,
                    status=getattr(error, "status", None),
                    errcode=getattr(error, "errcode", None),
                )
            if wait:
                await self.surface.sleep(wait)

    def _backoff(self, error: Exception, failures: int) -> float:
        if isinstance(error, MatrixError):
            if error.retry_after_ms is not None:
                return error.retry_after_ms / 1000
            if error.unauthorized:
                return IDLE_SECONDS
        return BACKOFF_SECONDS[min(failures, len(BACKOFF_SECONDS) - 1)]

    @asynccontextmanager
    async def _bound(self) -> AsyncIterator[SurfaceContext | None]:
        """The listener gate for this bot. The gate reports lost ownership as a bare `RuntimeError`
        on entry; only that entry is read as `FleetOwnershipLost`, so a `RuntimeError` from the body
        backs this bot off like any other failure."""
        async with AsyncExitStack() as stack:
            try:
                ctx = await stack.enter_async_context(self.listener.workspace(self.bot))
            except RuntimeError as error:
                raise FleetOwnershipLost(str(error)) from error
            yield ctx

    async def step(self) -> float:
        """One sync round, returning how long to wait before the next. An unbound bot or an empty
        slot waits and asks again, since both are fixed by a member in chat, not by a restart. The
        first round of a stream only fixes where it stands: history from before the bot was
        listening founds nothing."""
        async with self._bound() as ctx:
            if ctx is None:
                log("matrix.unbound", installation=self.bot)
                return IDLE_SECONDS
            try:
                homeserver = await ctx.credential(HOMESERVER_SLOT)
                token = await ctx.credential(TOKEN_SLOT)
            except CredentialSlotUnset as unset:
                log("matrix.slot_empty", installation=self.bot, slot=unset.args[0])
                return IDLE_SECONDS
            since = await read_since(ctx, self.bot)
        async with self.surface.client(homeserver, token) as client:
            batch = await client.sync(since)
            async with self._bound() as ctx:
                if ctx is None:
                    return IDLE_SECONDS
                await self.deliver(ctx, client, batch, since)
                await write_since(ctx, self.bot, next_batch(batch))
        return 0.0

    async def deliver(
        self,
        ctx: SurfaceContext,
        client: MatrixClient,
        batch: Mapping[str, Any],
        since: str | None,
    ) -> None:
        """Hear every message in the batch and admit the ones that found a turn. A message that
        fails is logged and skipped, so one bad event never holds the stream; a homeserver error
        or any database failure raises, and the batch is read again. A database failure reaches
        here through the session `write_since` then writes through, so that session's state is not
        knowably intact whatever caused it: a failure that recurs parks the stream and names itself
        every cycle, rather than dropping a member's message and advancing the position past it."""
        admitting = since is not None
        roster = Roster(ctx)
        self.names.update(room_names(batch))
        for room_id, inviter in invites(batch, self.bot):
            await self._invited(roster, client, room_id, inviter)
        earlier = await self._backfill(client, batch, since) if since is not None else {}
        joined: dict[str, frozenset[str]] = {}
        for room_id, event in timeline(batch, earlier):
            message = room_message(room_id, event)
            if message is None:
                continue
            own = message.sender == self.bot
            heard = self.heard.setdefault(room_id, deque(maxlen=AMBIENT_HISTORY_MESSAGES))
            prior = tuple(heard)
            entry = Heard(AmbientMessage(speaker=message.sender, text=message.body, own=own))
            heard.append(entry)
            if own or not admitting:
                continue
            if room_id not in joined:
                try:
                    joined[room_id] = await client.joined_members(room_id)
                except MatrixError as error:
                    if not _refused(error):
                        raise
                    log("matrix.room_unreadable", installation=self.bot, status=error.status)
                    joined[room_id] = frozenset()
            if not joined[room_id]:
                continue
            try:
                entry.admitted = await self.consider(ctx, roster, message, prior, joined[room_id])
            except sa.exc.SQLAlchemyError:
                raise
            except Exception as error:
                warn(
                    "matrix.message_skipped",
                    installation=self.bot,
                    error_class=type(error).__name__,
                )

    async def _backfill(
        self, client: MatrixClient, batch: Mapping[str, Any], since: str
    ) -> dict[str, list[Mapping[str, Any]]]:
        """The messages each cut-short room held between `since` and its timeline, oldest first,
        walked back at most `BACKFILL_PAGES` pages. A room the bot can no longer read is left
        with its timeline alone."""
        earlier: dict[str, list[Mapping[str, Any]]] = {}
        for room_id, start in gaps(batch).items():
            found: list[Mapping[str, Any]] = []
            page: str | None = start
            for _ in range(BACKFILL_PAGES):
                if page is None:
                    break
                try:
                    events, page = await client.messages_before(room_id, page, since)
                except MatrixError as error:
                    if not _refused(error):
                        raise
                    log("matrix.backfill_refused", installation=self.bot, status=error.status)
                    break
                found.extend(events)
            if page is not None:
                log("matrix.backfill_bounded", installation=self.bot, pages=BACKFILL_PAGES)
            earlier[room_id] = found[::-1]
        return earlier

    async def _invited(
        self, roster: Roster, client: MatrixClient, room_id: str, inviter: str
    ) -> None:
        """Join a room a workspace member invited the bot to; an invitation from anyone else is
        left standing."""
        if await roster.member(inviter) is None:
            log("matrix.invite_left", installation=self.bot, inviter_server=_server(inviter))
            return
        try:
            await client.join(room_id)
        except MatrixError as error:
            if not _refused(error):
                raise
            log("matrix.join_refused", installation=self.bot, status=error.status)

    async def consider(
        self,
        ctx: SurfaceContext,
        roster: Roster,
        message: RoomMessage,
        prior: Sequence[Heard],
        joined: frozenset[str],
    ) -> bool:
        """Admit one message or decline it, returning whether it founded or joined a turn. A sender
        who is no member is declined before anything is spent on the line."""
        addressed = (len(joined) == 2 and self.bot in joined) or message.addresses(self.bot)
        if not addressed and await ctx.find_conversation(message.room_id) is None:
            return False
        member_id = await roster.member(message.sender)
        if member_id is None:
            log("matrix.speaker_unresolved", installation=self.bot)
            return False
        if not addressed:
            asked = AmbientMessage(speaker=message.sender, text=message.body)
            if not await ctx.ambient_reply_wanted(asked, tuple(h.line for h in prior)):
                log("matrix.ambient_declined", installation=self.bot)
                return False
        audience = audience_for(message.room_id, await roster.internal(self.bot, joined))
        conversation_id = await ctx.conversation_for(
            message.room_id, audience, label=self.names.get(message.room_id)
        )
        marker = mint_marker()
        await ctx.admit(
            conversation_id,
            fence_member_message(marker, room_context(marker, prior), message.body, ""),
            idempotency_key=message.event_id,
            context=TurnContext(
                sender=message.sender, source=permalink(message.room_id, message.event_id)
            ),
            speaker_member_id=member_id,
        )
        return True
