# ufo-ext-matrix

A Matrix chat surface for [ufo](https://github.com/ufo-ai/ufo-core): a room is a conversation, and
the people in it are members.

The surface is durable, like Slack's. A bot user reads its rooms over the client-server `/sync`
stream, and each finished turn is one message back into the room it came from.

## What it adds

A room is mostly not addressed to the agent, so the surface decides per message whether it founds a
turn:

| Message | Turn |
| --- | --- |
| From a sender who resolves to no member | None, and no reply — unless it is a code proving that sender's MXID |
| Mentions the bot, or is sent in a direct room (the bot and one other) | Founded |
| Unaddressed, in a room that already holds a conversation | Founded only if `ambient_reply_wanted` says the agent is wanted |
| Unaddressed, in a room with no conversation yet | None |
| The bot's own echo, an `m.notice`, an edit (`m.replace`), a redaction, a redacted or encrypted event | None |

Unaddressed lines the agent did not take part in ride the next admitted message as room context, and
the recent ones are the evidence the ambient decision reads.

| Matrix | ufo |
| --- | --- |
| Bot MXID | The installation, bound to one workspace |
| Room id | The conversation's key |
| Sender MXID | A member: linked on first contact when its homeserver is the workspace's own domain and `localpart@domain` is a member's email, or linked by a code the member proved it with; otherwise nobody |
| Room where everyone but the bot is a member | A room audience: the room's memory and the workspace's shared memory |
| Room with anyone else in it, or in a workspace with no domain | A foreign audience: the room's memory alone, nothing internal |
| Terminal turn | `PUT /rooms/{roomId}/send/m.room.message/ufo-{turn_id}` |

A direct room is a room like any other, so a room's audience only ever narrows: once anyone who is
not a member joins, the room is foreign for good, whoever leaves after.

The transaction id is the turn's, so a retried delivery is the same transaction and the homeserver
answers it with the event it already sent. A turn whose whole answer is silence sends nothing. A
question is written out with numbered options; a connect or credential handoff, and a turn's shared
files, point at the workspace, since a room carries none of them. A cancelled turn posts the reason
core gave — an archived conversation, a removed seat — or, with none, that it was stopped.

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

- **An unlisted bot is bound but deaf.** The listener runs only the MXIDs `UFO_MATRIX_BOTS` names;
  binding one the deploy does not list admits nothing until it does.
- **Encrypted rooms are silent.** The surface reads unencrypted rooms only. In an encrypted room it
  hears nothing it can read, and admits nothing.
- **A new token is a new transaction scope.** Transaction ids are idempotent per access token, so a
  reply retried across a token rotation can land twice.
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
- **A room of more than 50 others is foreign.** Every joined user is resolved to a member before a
  room reads internal memory, and past 50 the surface does not ask.
- **A long gap is heard in part.** Past the 500 messages its history pages reach, a gap after a long
  outage is heard from its newest end; anything earlier founds nothing.

## Tests

```bash
pytest extensions/matrix
```

`test_matrix_contracts.py` needs only `pytest`: the import gate, and which events may found a turn.
`test_matrix_surface.py` drives the listener and the post against a fake homeserver,
`test_matrix_linking.py` drives a claim through its proof the same way, and
`test_matrix_registry.py` loads the installed entry point through ufo's loader and applies the
migrations; all three skip where `ufo` is absent.

## License

Apache-2.0.
