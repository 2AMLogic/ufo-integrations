# ufo-ext-matrix

A Matrix chat surface for [ufo](https://github.com/ufo-ai/ufo-core): a room is a conversation, and
the people in it are members.

The surface is durable, like Slack's. A bot user reads its rooms over the client-server `/sync`
stream, and a turn answers in the room it came from: its reply as rich text under the message it
answers, the files it shared as messages of their own, and the words it marks before it ends as they
are marked. While it works, the room shows it working; when it ends in a question, the room answers
by typing a label or tapping a poll.

## What it adds

A room is mostly not addressed to the agent, so the surface decides per message whether it founds a
turn:

| Message | Turn |
| --- | --- |
| From a sender who resolves to no member | None, and no reply — unless it is a code proving that sender's MXID |
| Addressed to the bot, or sent in a direct room (the bot and one other) | Founded |
| Unaddressed, in a room that already holds a conversation | Founded only if `ambient_reply_wanted` says the agent is wanted |
| Unaddressed, in a room with no conversation yet | None |
| The bot's own echo, an `m.notice`, an edit (`m.replace`), a redaction, a redacted or encrypted event | None |

A message is addressed to the bot four ways, and each names the bot whole, so a mention of `@ufobot`
addresses nobody named `@ufo`:

| Addressed by | Read from |
| --- | --- |
| An intentional mention | `m.mentions.user_ids` |
| A pill a client rendered instead | `https://matrix.to/#/<bot mxid>` in `formatted_body` |
| The bot's MXID or display name in the words | `body`, whatever its case |
| A reply to something the bot said | `m.in_reply_to` naming a message of the bot's |

Unaddressed lines the agent did not take part in ride the next admitted message as room context, and
the recent 20 are the evidence the ambient decision reads.

| Matrix | ufo |
| --- | --- |
| Bot MXID | The installation, bound to one workspace |
| Room id | The conversation's key |
| Sender MXID | A member: linked on first contact when its homeserver is the workspace's own domain and `localpart@domain` is a member's email, or linked by a code the member proved it with; otherwise nobody |
| Room where everyone but the bot is a member | A room audience: the room's memory and the workspace's shared memory |
| Room with anyone else in it, or in a workspace with no domain | A foreign audience: the room's memory alone, nothing internal |
| Terminal turn | `PUT /rooms/{roomId}/send/m.room.message/ufo-{turn_id}` |
| The message that founded the turn | `m.in_reply_to`, or `m.thread` under its root where the member spoke in a thread |
| Markdown the turn wrote | `formatted_body` in `org.matrix.custom.html`, beside the words in `body` |
| A shared file | `POST /_matrix/media/v3/upload`, then `m.image` / `m.video` / `m.audio` / `m.file` under the reply |
| A detailed write-up | A link in the reply to the portal, never an upload |
| Words marked mid-turn | One message each, under `ufo-say-{reply_id}` |
| A terminal `ask_user` | The words, its questions as a labelled list, and an `m.poll.start` where one question takes one choice |
| A reply of labels, or a tap on the poll | The options it names, admitted under that event's id |
| The answer that landed | An `m.replace` of the question, marking what was chosen, under `ufo-answered-{event_id}` |
| A turn that is running | `POST .../receipt/m.read/{eventId}`, then `PUT .../typing/{userId}` refreshed until the turn ends |

A direct room is a room like any other, so a room's audience only ever narrows: once anyone who is
not a member joins, the room is foreign for good, whoever leaves after.

The transaction id is the turn's, so a retried delivery is the same transaction and the homeserver
answers it with the event it already sent. Each file is sent under `ufo-file-{turn_id}-{artifact_id}`
and each mid-turn reply under `ufo-say-{reply_id}`, so a delivery recovered after a crash re-sends
none of them. A turn whose whole answer is silence sends nothing. A question is written out with
numbered options; a connect or credential handoff points at the workspace, since a room carries
neither. A cancelled turn posts the reason core gave — an archived conversation, a removed seat — or,
with none, that it was stopped.

A whole event weighs at most 65536 bytes and a reply carries its words twice, so a reply over 4096
bytes of Markdown is written in parts, cut between paragraphs and never leaving a code fence open.
The first part's event id is the reference core records, and every part relates to the same message.

Which room message a turn answers is stored per turn in `matrix_ext_answering`: a writeback names the
turn, the room, and the member, so admission records the event id every later message of that turn
relates to. An answer is a message like any other, so the turn it founds answers the answer, and its
reply lands under that.

The typing indicator runs off `tail(turn_id)` and stops on the turn's terminal or parked frame. The
`PUT` carries the homeserver's own timeout and is refreshed under it, so a stream that drops leaves
the indicator to the server's clock rather than leaving a room typing.

The `/sync` position is stored per workspace in `matrix_ext_since`, a table the extension's
migration owns, after each batch is delivered. A restart resumes from it; a batch replayed after a
crash is admitted once, because each message's event id is its admission key. The first sync of a
stream only fixes where it stands — history from before the bot listened founds nothing.

A room that saw more than 50 events between two syncs comes back `limited`. The surface pages its
history back from the gap to where the stream stood, 100 messages a page for at most 5 pages, and
hears what it finds ahead of the timeline. A message that fails to admit is logged by error class and
skipped, and one bot's failure backs that bot off without stopping the others.

## Linking a Matrix ID

A member whose MXID lives on another homeserver — a public one, say — links it by proving they hold
it. The member asks in chat, on any surface; `matrix_link_account` records a claim on the MXID and
answers with a one-time code, and the member sends that code to the bot from the MXID, in a direct
room with the bot alone. The bot never writes first.

| Step | What happens |
| --- | --- |
| Claim | A code of 8 characters, live for 15 minutes, stored as a salted slow hash; a new claim on the same MXID replaces the old code |
| Invite | While a claim is live, the bot joins a room the claimed MXID invites it to; with none, the invitation is left standing |
| Proof | The right code from the claimed MXID links it to the member who claimed it; the bot answers in the room, and the message founds no turn |
| Wrong code | Answered with the tries left; the fifth wrong code voids the claim |
| Expired | Answered once, and the claim is gone |
| Next message | Founds a turn as that member |

A code in a room with anyone else in it, or from any other MXID, proves nothing and is not answered.
The proving message's event id is kept, so a batch replayed after a crash does not admit it.

An admin unlinks an MXID with `matrix_unlink_account`. From then on it speaks for nobody — a
domain-matched MXID included — until someone proves it again with a code. Claims and unlinks live in
`matrix_ext_claim` and `matrix_ext_link`, the extension's own tables; the link itself is core's.

## How a room answers a question

A room has no buttons, so a question is a numbered list, and a reply that is nothing but labels is the
answer. Anything else is words — which is how a member answers a question that asked for words, and
how they say something that merely starts with a number.

| Ask | Labels | Answered by |
| --- | --- | --- |
| One question | `1`, `2` | `2`, or `1, 3` where the question takes several |
| Up to four questions | `1a`, `2b` | `1a 2b`, one label per question |

A question that takes one choice keeps the first label its reply names. `answerable_question` is the
only gate on who may answer what: a question already answered, one past the ask's own range, and one
put to another member are each refused there, and the reply is admitted as the words it is.

## Install

```bash
pip install "ufo-integrations @ git+https://github.com/2AMLogic/ufo-integrations"
ufoctl ext install matrix
```

| Setting | Where | Holds |
| --- | --- | --- |
| `UFO_MATRIX_BOTS` | Deploy environment | The bot MXIDs this deploy's listener runs, comma-separated |
| `matrix_homeserver` | Workspace credential slot | The homeserver's base URL, e.g. `https://matrix.example.org` |
| `matrix_access_token` | Workspace credential slot | The bot user's access token |

## Connect

Setup happens in chat. `matrix_connect` is an instance action bound to the `matrix` surface, offered
on that one surface row as `action:surface:matrix_connect`, and the `matrix-setup` skill carries the
order of the steps.

| Step | In chat |
| --- | --- |
| The two slots | The agent calls core's `request_credentials` for `matrix_homeserver` and `matrix_access_token`, so the token is filled where the transcript cannot see it |
| Connect | `GET /_matrix/client/v3/account/whoami` names the bot the token belongs to, and that MXID is bound as the workspace's installation |
| Invite | A workspace member invites the bot to a room and it joins itself, as does an MXID a member is proving; an invitation from anyone else is left standing |

The bot the token belongs to is the bot that gets bound, so a wrong token is a refusal and never a
wrong binding. A second token for the same bot replaces the binding, and the listener reads the
binding each sync round, so a connect takes effect without a restart. A bot another workspace already
holds is refused by name — that MXID belongs elsewhere, and which workspace holds it is not this
workspace's to know.

## Traps

- **A reply of labels is an answer, and one label with a word is not.** `1` answers; `1 more thing`
  is words. A member who means the first option and says so in a sentence is heard as a sentence,
  which is the reading that never puts words the agent invented in their mouth.
- **A question put to one member does not silence the others.** Another member's `1` is admitted as
  the words it is, the question stays open, and only the member it names answers it.
- **A question is marked by the stream that heard it asked.** The rewrite needs the message the bot
  asked in, which the stream learns by hearing the bot's own line; a stream restarted between the
  question and its answer admits the answer and leaves the list unmarked.
- **A poll carries one question and one choice.** An ask of several questions, or one that takes
  several answers, reaches the room as the labelled list alone.
- **Typing is not delivery.** The hub is lossy, so a frame that never arrives costs the room an
  indicator and never the turn's answer — and a reporter the stream cancels leaves the indicator to
  the homeserver's timeout rather than sending a last stop.
- **An unlisted bot is bound but deaf.** The listener runs only the MXIDs `UFO_MATRIX_BOTS` names;
  binding one the deploy does not list admits nothing until it does.
- **Encrypted rooms are silent.** The surface reads unencrypted rooms only. In an encrypted room it
  hears nothing it can read, and admits nothing.
- **A new token is a new transaction scope.** Transaction ids are idempotent per access token, so a
  reply retried across a token rotation can land twice.
- **A file is best effort.** One upload the homeserver refuses is logged by error class and its
  siblings still land, so a room can hold three of four files and the reply that named all four.
- **An orphaned upload is the cost of at-least-once.** Recovery repeats `attach`, so bytes can reach
  the media repository twice; the second `mxc://` is unreferenced and the repository keeps it.
- **A write-up needs a portal.** The detailed report is a link into the deploy's portal, and a deploy
  without one, or a room the portal shows nobody, points at the workspace instead — the reply never
  carries an empty body for a write-up the room cannot link.
- **Only a member brings the bot into a room.** An invitation from anyone who resolves to no member —
  a stranger on the bot's own homeserver included — is left standing, unless a member's claim on
  that MXID is live.
- **An MXID links to one member for good.** Core records the first member an MXID is linked to and
  offers no call that moves it. An admin's unlink silences the MXID, but proving it again links it
  back to that same member only; a claim by anyone else is refused.
- **A claim opens the door to its MXID.** While it is live, the bot joins a room that MXID invites
  it to, whoever else is in the room. The room founds nothing until the MXID is proved, and a room
  with others in it is foreign.
- **A non-member is not answered.** A sender outside the workspace's domain, or on it with no member
  behind `localpart@domain`, founds no turn and gets no reply, however directly it addresses the bot.
  Nothing is spent on the line; it is still heard as room context for the members. The one exception
  is a code sent in a direct room for a claim on that sender's MXID.
- **A homeserver username is taken to be a mailbox.** First contact links `@alice:example.com` to
  the member `alice@example.com`, so the homeserver must hand out usernames only to the people who
  hold those mailboxes. Disable open registration on it, and keep its usernames equal to mail names —
  anyone who can register `@alice` before Alice does speaks as her.
- **A room of more than 50 others is foreign, and stays foreign.** Every joined user is resolved
  to a member before a room reads internal memory, and past 50 the surface does not ask. A room's
  audience only narrows: one that went foreign — past 50, or through a non-member who has since
  left — never reads internal memory again, however small the room gets.
- **Backfill can hear a room's pre-join past.** A room the bot joined inside a sync window can come
  back `limited`; its history pages then reach back to the stored position, and with a `shared`
  history visibility they hold messages sent before the join. A member's pre-join line that
  mentions the bot, or any line in a direct room, can found a turn. The surface accepts this
  deliberately: nothing before the stored position is ever read, and only a room joined within
  the window exposes pre-join lines.
- **A long gap is heard in part.** Past the 500 messages its history pages reach, a gap after a long
  outage is heard from its newest end; anything earlier founds nothing.

## Tests

```bash
pytest extensions/matrix
```

`test_matrix_contracts.py` needs only `pytest`: the import gate, which events may found a turn, who a
line addresses, the labels a question is answered by, and the HTML, splitting, and relations the
surface writes. `test_matrix_surface.py` drives the listener and the three delivery handlers against
a fake homeserver, `test_matrix_linking.py` drives a claim through its proof the same way, and
`test_matrix_registry.py` loads the installed entry point through ufo's loader and applies the
migrations; all three skip where `ufo` is absent.

`test_matrix_integration.py` drives the delivery handlers against a real homeserver, and is
collected only where `MATRIX_INTEGRATION_HOMESERVER` names one — CI never sets it, so the suite
there is unchanged and the registry job's no-skip rule holds. It registers its own throwaway users,
so the named homeserver must allow registration; a private Synapse container does. It needs `ufo`
installed, and runs for example as:

```bash
MATRIX_INTEGRATION_HOMESERVER=http://localhost:8017 \
  uv run --python 3.12 --with pytest --with "ufo @ file:///home/ubuntu/ufo-core" \
  pytest extensions/matrix/tests/test_matrix_integration.py -v
```

## License

Apache-2.0.
