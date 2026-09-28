"""The Matrix surface: a bot user's `/sync` stream in, and the room messages a turn becomes.

A room is a conversation, keyed by its room id; its speakers are members where one resolves. The
surface is durable and installation-routed — the installation id is the bot's MXID, bound to one
workspace — so ingress is the listener alone and no request is routed to it.

Most lines in a room are not addressed to the agent. A message from a member founds a turn when it
mentions the bot, when it is sent in a direct room (the bot and one other), or when the room already
holds a conversation and `ambient_reply_wanted` says the agent is wanted; anything else is heard,
kept as evidence for the next decision, and admits nothing. A sender who resolves to no member
founds nothing, however it addresses the bot; the one thing the bot reads from it is a code proving
its MXID for a member who claimed it (`linking.py`).

What a turn sends back is three handlers over one transport: `post` writes the terminal reply,
`attach` follows it with the turn's shared files, and `speak` delivers the words a turn marks before
it ends. Each relates its messages to the room message the turn answers, which admission recorded
(`answering.py`), so a reply lands as a reply and a threaded conversation stays in its thread."""

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
    MidTurnReply,
    NothingDelivered,
    SharedArtifact,
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
from ufo_ext_matrix.answering import Answering, read_answering, write_answering
from ufo_ext_matrix.client import MatrixClient, MatrixError
from ufo_ext_matrix.events import (
    NOTICE_MSGTYPE,
    SURFACE,
    TEXT_MSGTYPE,
    RoomMessage,
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
from ufo_ext_matrix.linking import Linking, code_in, proof_txn, unlinked
from ufo_ext_matrix.messages import (
    file_content,
    message_content,
    msgtype_for,
    parts,
    reply_relation,
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
REPORT_LINK_TEXT = "Open detailed report"
FILE_ROLE = "file"
DETAILS_ROLE = "details"


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


def reply_text(
    writeback: Writeback,
    workspace_url: str | None,
    reports: Sequence[str] = (),
    *,
    unlinked: bool = False,
) -> str:
    """The one message a terminal turn becomes. A failed turn says so in the surface's own words; a
    cancelled turn posts the reason core gave — an archived conversation, a revoked seat — or, with
    none, says it was stopped; a detailed write-up is a link under the words the turn wrote it
    under, or points at the workspace where the deploy offers no link; a question is written out
    with its options, since a room has no buttons; and what a room cannot carry — a connect or
    credential handoff, a shared file — points at the workspace."""
    terminal = writeback.terminal
    text = terminal.text.strip()
    if terminal.status == "failed":
        return FAILED_LINE
    if terminal.status == "cancelled":
        return text if text and not is_silence_sentinel(text) else CANCELLED_LINE
    said: list[str] = []
    if text and not is_silence_sentinel(text):
        said.append(text)
    said.extend(reports)
    if terminal.question is not None:
        for asked in terminal.question.questions:
            options = asked.options or ()
            lines = [asked.question, *(f"{n}. {o.label}" for n, o in enumerate(options, 1))]
            said.append("\n".join(lines))
    where = f": {workspace_url}" if workspace_url else "."
    if terminal.connect_request is not None or terminal.credential_request is not None:
        said.append(ELSEWHERE_LINE + where)
    if any(artifact.role == FILE_ROLE for artifact in writeback.artifacts) or unlinked:
        said.append(FILES_LINE + where)
    return "\n\n".join(said)


def shared_files(writeback: Writeback) -> tuple[SharedArtifact, ...]:
    """The files a turn shared, which a room carries as messages of their own. A detailed write-up
    is not one of them: it reaches the member as the link the reply carries."""
    return tuple(a for a in writeback.artifacts if a.role == FILE_ROLE)


async def report_links(ctx: SurfaceContext, writeback: Writeback) -> tuple[str, ...]:
    """The detailed write-ups this reply links to, under the words the turn linked them with or the
    surface's own where it named none. A deploy whose portal shows nobody this conversation offers
    no link, and the write-up reaches the member through the workspace instead."""
    links: list[str] = []
    for artifact in writeback.artifacts:
        if artifact.role != DETAILS_ROLE:
            continue
        url = await ctx.report_url(writeback.conversation_id, artifact)
        if url is None:
            continue
        links.append(f"[{artifact.subject or REPORT_LINK_TEXT}]({url})")
    return tuple(links)


@asynccontextmanager
async def delivering() -> AsyncIterator[None]:
    """Every homeserver failure a writeback handler meets, as the delivery error core retries on: a
    rate limit carries the wait the homeserver itself asked for, and nothing repeats the body of the
    answer the homeserver sent."""
    try:
        yield
    except MatrixError as error:
        retry = error.retry_after_ms
        raise SurfaceDeliveryError(
            str(error), retry_after_seconds=None if retry is None else math.ceil(retry / 1000)
        ) from None
    except httpx.HTTPError as error:
        raise SurfaceDeliveryError(f"send failed: {type(error).__name__}") from None


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
    server does for addresses. An MXID an admin unlinked, and any other, is nobody."""

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
        if await unlinked(self.ctx, mxid):
            return None
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
    linking: Linking = field(default_factory=Linking)

    def client(self, homeserver: str, access_token: str) -> MatrixClient:
        return MatrixClient(homeserver, access_token, transport=self.transport)

    async def listen(self, listener: SurfaceListenerContext) -> None:
        bots = installations(self.environ.get(BOTS_ENV, ""))
        if not bots:
            log("matrix.no_installations", env=BOTS_ENV)
            await asyncio.Event().wait()
        await asyncio.gather(*(Installation(self, listener, bot).run() for bot in bots))

    async def slots(self, ctx: SurfaceContext) -> tuple[str, str]:
        """The workspace's homeserver and its bot's token. An empty slot is a delivery failure:
        a member fills it in chat, and the writeback waits for them."""
        try:
            return await ctx.credential(HOMESERVER_SLOT), await ctx.credential(TOKEN_SLOT)
        except CredentialSlotUnset as unset:
            raise SurfaceDeliveryError(f"matrix slot {unset.args[0]} is empty") from None

    async def post(self, ctx: SurfaceContext, writeback: Writeback) -> str | NothingDelivered:
        """The turn's answer as the room reads it: the words, the same words as HTML, and a relation
        to the message the turn answers. A reply longer than one event carries is written in parts,
        and the first part's event id is the reference core records — what `attach` hangs the turn's
        files under, whatever else the reply became."""
        if writeback_says_nothing(writeback):
            return NOTHING_DELIVERED
        links = await report_links(ctx, writeback)
        details = sum(1 for artifact in writeback.artifacts if artifact.role == DETAILS_ROLE)
        body = reply_text(writeback, ctx.home_url(), links, unlinked=details > len(links))
        homeserver, token = await self.slots(ctx)
        answering = await read_answering(ctx, writeback.turn_id)
        async with delivering():
            async with self.client(homeserver, token) as client:
                return await self.say(
                    client, writeback.queue_key, txn_id(writeback.turn_id), body, answering
                )

    async def attach(self, ctx: SurfaceContext, writeback: Writeback, reply_ref: str) -> None:
        """The turn's shared files, each its own message under the reply core recorded. Every file
        is best effort: a refusal the homeserver will not take back is logged and the rest go on,
        since a room that carries three of four files says more than one that carries none — but a
        failure a retry can fix, a rate limit or a lost database among them, raises, so the file is
        not discarded to a transient outage. Delivery repeats after a crash, and a file already
        sent is sent under the transaction id it was sent under before."""
        files = shared_files(writeback)
        if not files:
            return
        homeserver, token = await self.slots(ctx)
        answering = await read_answering(ctx, writeback.turn_id)
        thread = answering.thread_root if answering is not None else None
        relation = reply_relation(reply_ref, thread)
        async with self.client(homeserver, token) as client:
            for artifact in files:
                try:
                    await self.hand_over(ctx, client, writeback, artifact, relation)
                except MatrixError as error:
                    if error.retry_after_ms is not None or error.status >= 500:
                        retry = error.retry_after_ms
                        raise SurfaceDeliveryError(
                            str(error),
                            retry_after_seconds=(
                                None if retry is None else math.ceil(retry / 1000)
                            ),
                        ) from None
                    warn(
                        "matrix.file_undelivered",
                        media_type=artifact.media_type,
                        error_class=type(error).__name__,
                        status=error.status,
                    )
                except sa.exc.SQLAlchemyError:
                    raise
                except httpx.HTTPError as error:
                    raise SurfaceDeliveryError(f"send failed: {type(error).__name__}") from None
                except Exception as error:
                    warn(
                        "matrix.file_undelivered",
                        media_type=artifact.media_type,
                        error_class=type(error).__name__,
                    )

    async def hand_over(
        self,
        ctx: SurfaceContext,
        client: MatrixClient,
        writeback: Writeback,
        artifact: SharedArtifact,
        relation: Mapping[str, Any],
    ) -> None:
        """One shared file into the room: its bytes to the media repository, then the message that
        carries the `mxc://` the repository answered. A repeated upload leaves an unreferenced
        object behind, which the media repository is welcome to."""
        data = await ctx.blob.get(artifact.blob_key)
        url = await client.upload(artifact.filename, artifact.media_type, data)
        await client.send_message(
            writeback.queue_key,
            file_txn_id(writeback.turn_id, artifact.id),
            file_content(
                msgtype_for(artifact.media_type),
                artifact.filename,
                artifact.subject,
                artifact.media_type,
                artifact.size_bytes,
                url,
                relation,
            ),
        )

    async def speak(self, ctx: SurfaceContext, reply: MidTurnReply) -> str:
        """One reply delivered while the turn is still running, under the same relation its terminal
        reply will carry. A notice core sends because a member commented from another surface is the
        room's own aside rather than the agent's words, so the room reads it as one."""
        homeserver, token = await self.slots(ctx)
        answering = await read_answering(ctx, reply.turn_id)
        msgtype = NOTICE_MSGTYPE if reply.is_comment else TEXT_MSGTYPE
        async with delivering():
            async with self.client(homeserver, token) as client:
                return await self.say(
                    client,
                    reply.queue_key,
                    say_txn_id(reply.id),
                    reply.text,
                    answering,
                    msgtype=msgtype,
                )

    async def say(
        self,
        client: MatrixClient,
        room_id: str,
        base: str,
        body: str,
        answering: Answering | None,
        msgtype: str = TEXT_MSGTYPE,
    ) -> str:
        """One message, or the parts of one too long to be one, in order. Every part relates to the
        same message, so a client threading the reply threads all of it, and the first part's event
        id is the reference the caller returns."""
        relation = (
            None if answering is None else reply_relation(answering.event_id, answering.thread_root)
        )
        sent: list[str] = []
        for part, text in enumerate(parts(body), 1):
            sent.append(
                await client.send_message(
                    room_id, part_txn_id(base, part), message_content(text, msgtype, relation)
                )
            )
        return sent[0]

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
                if await self._proved(ctx, client, roster, message, joined[room_id]):
                    heard.pop()
                    continue
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
        """Join a room a workspace member invited the bot to, or one an MXID a member is proving
        invited it to; an invitation from anyone else is left standing."""
        claimed = self.surface.linking.live_claim
        if await roster.member(inviter) is None and not await claimed(roster.ctx, inviter):
            log("matrix.invite_left", installation=self.bot, inviter_server=_server(inviter))
            return
        try:
            await client.join(room_id)
        except MatrixError as error:
            if not _refused(error):
                raise
            log("matrix.join_refused", installation=self.bot, status=error.status)

    async def _proved(
        self,
        ctx: SurfaceContext,
        client: MatrixClient,
        roster: Roster,
        message: RoomMessage,
        joined: frozenset[str],
    ) -> bool:
        """Whether a direct message was a code proving its sender's MXID. It is answered in the
        room and founds no turn."""
        if joined != {self.bot, message.sender} or code_in(message.body) is None:
            return False
        proof = await self.surface.linking.prove(ctx, message, roster.member)
        if proof is None:
            return False
        if proof.member_id is not None:
            roster.known[message.sender] = proof.member_id
        log("matrix.proof_read", installation=self.bot, linked=proof.member_id is not None)
        await client.send_message(
            message.room_id, proof_txn(message.event_id), message_content(proof.reply, TEXT_MSGTYPE)
        )
        return True

    async def consider(
        self,
        ctx: SurfaceContext,
        roster: Roster,
        message: RoomMessage,
        prior: Sequence[Heard],
        joined: frozenset[str],
    ) -> bool:
        """Admit one message or decline it, returning whether it founded or joined a turn. A sender
        who is no member is declined before anything is spent on the line. An admitted message is
        recorded as the one its turn answers, since the writeback that answers it names the turn and
        the room but not the event, and every message the turn sends back relates to this one."""
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
        admitted = await ctx.admit(
            conversation_id,
            fence_member_message(marker, room_context(marker, prior), message.body, ""),
            idempotency_key=message.event_id,
            context=TurnContext(
                sender=message.sender, source=permalink(message.room_id, message.event_id)
            ),
            speaker_member_id=member_id,
        )
        try:
            await write_answering(
                ctx,
                admitted.turn_id,
                Answering(
                    room_id=message.room_id,
                    event_id=message.event_id,
                    thread_root=message.thread_root,
                ),
            )
        except sa.exc.SQLAlchemyError:
            raise
        except Exception as error:
            # The turn stands without the record: the reply then relates to nothing, and the line
            # is not fed back as room context for a turn it founded.
            warn("matrix.answering_unrecorded", error_class=type(error).__name__)
        return True
