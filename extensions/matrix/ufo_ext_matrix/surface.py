"""The Matrix surface: a bot user's `/sync` stream in, one room message out per terminal turn.

A room is a conversation, keyed by its room id; its speakers are members where one resolves. The
surface is durable and installation-routed — the installation id is the bot's MXID, bound to one
workspace — so ingress is the listener alone and no request is routed to it.

Most lines in a room are not addressed to the agent. A message founds a turn when it mentions the
bot, when it is sent in a direct room (the bot and one other), or when the room already holds a
conversation and `ambient_reply_wanted` says the agent is wanted; anything else is heard, kept as
evidence for the next decision, and admits nothing."""

import asyncio
import math
import os
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel

from ufo.sdk.audience import (
    Audience,
    conversation_audience,
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

FAILED_LINE = "This turn failed before it could answer."
CANCELLED_LINE = "This turn was stopped."
ELSEWHERE_LINE = "The next step happens in the workspace"
FILES_LINE = "This turn shared files, which are in the workspace"


class ConnectInput(BaseModel):
    """Nothing: the bot is whoever the workspace's access token belongs to."""


def installations(configured: str) -> tuple[str, ...]:
    """The bot MXIDs a deploy names, comma- or space-separated, in order and once each."""
    named = configured.replace(",", " ").split()
    return tuple(dict.fromkeys(named))


def reply_text(writeback: Writeback, workspace_url: str | None) -> str:
    """The one message a terminal turn becomes. A failed or stopped turn says so in the surface's
    own words; a question is written out with its options, since a room has no buttons; and what a
    room cannot carry — a connect or credential handoff, a shared file — points at the workspace."""
    terminal = writeback.terminal
    if terminal.status == "failed":
        return FAILED_LINE
    if terminal.status == "cancelled":
        return CANCELLED_LINE
    parts: list[str] = []
    text = terminal.text.strip()
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


def audience_for(
    bot: str, room_id: str, joined: frozenset[str], direct: bool, member_id: UUID | None
) -> Audience:
    """Who a room's conversation may disclose to. A room with anyone joined from another homeserver
    is foreign and reads nothing internal; a direct room with a known member is that member's; any
    other room is a room."""
    home = server_name(bot)
    key = room_key(room_id)
    if any(_server(mxid) != home for mxid in joined):
        return foreign_room_audience(SURFACE, key)
    if direct and member_id is not None:
        return conversation_audience(member_id)
    return room_audience(SURFACE, key)


def _server(mxid: str) -> str | None:
    try:
        return server_name(mxid)
    except ValueError:
        return None


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
        tail = "It is listening." if listed else f"It listens once the deploy's {BOTS_ENV} names it."
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
        failures = 0
        while True:
            try:
                wait = await self.step()
                failures = 0
            except (MatrixError, httpx.HTTPError) as error:
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

    async def step(self) -> float:
        """One sync round, returning how long to wait before the next. An unbound bot or an empty
        slot waits and asks again, since both are fixed by a member in chat, not by a restart. The
        first round of a stream only fixes where it stands: history from before the bot was
        listening founds nothing."""
        async with self.listener.workspace(self.bot) as ctx:
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
            async with self.listener.workspace(self.bot) as ctx:
                if ctx is None:
                    return IDLE_SECONDS
                await self.deliver(ctx, client, batch, admitting=since is not None)
                await write_since(ctx, self.bot, next_batch(batch))
        return 0.0

    async def deliver(
        self,
        ctx: SurfaceContext,
        client: MatrixClient,
        batch: Mapping[str, Any],
        *,
        admitting: bool,
    ) -> None:
        self.names.update(room_names(batch))
        for room_id, inviter in invites(batch, self.bot):
            await self._invited(client, room_id, inviter)
        joined: dict[str, frozenset[str]] = {}
        for room_id, event in timeline(batch):
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
                joined[room_id] = await client.joined_members(room_id)
            entry.admitted = await self.consider(ctx, message, prior, joined[room_id])

    async def _invited(self, client: MatrixClient, room_id: str, inviter: str) -> None:
        """Join a room a user of the bot's own homeserver invited it to; an invitation from any
        other server is left standing."""
        if _server(inviter) != server_name(self.bot):
            log("matrix.invite_left", installation=self.bot, inviter_server=_server(inviter))
            return
        await client.join(room_id)

    async def consider(
        self,
        ctx: SurfaceContext,
        message: RoomMessage,
        prior: Sequence[Heard],
        joined: frozenset[str],
    ) -> bool:
        """Admit one message or decline it, returning whether it founded or joined a turn."""
        direct = len(joined) == 2 and self.bot in joined
        if not direct and not message.addresses(self.bot):
            if await ctx.find_conversation(message.room_id) is None:
                return False
            asked = AmbientMessage(speaker=message.sender, text=message.body)
            if not await ctx.ambient_reply_wanted(asked, tuple(h.line for h in prior)):
                log("matrix.ambient_declined", installation=self.bot)
                return False
        member_id = await self.member(ctx, message.sender)
        audience = audience_for(self.bot, message.room_id, joined, direct, member_id)
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

    async def member(self, ctx: SurfaceContext, sender: str) -> UUID | None:
        """The member an MXID speaks as. A linked MXID is its member; on first contact an MXID on
        the workspace's own domain links to the member whose email is `localpart@domain` — the
        homeserver serving that domain vouches for its users as the mail server does for addresses.
        Any other sender speaks as nobody."""
        linked = await ctx.linked_member(sender)
        if linked is not None:
            return linked
        domain = await ctx.workspace_domain()
        if domain is None or _server(sender) != domain:
            return None
        return await ctx.link_member(sender, f"{localpart(sender)}@{domain}")
