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
| Sender MXID | A member: linked on first contact when its homeserver is the workspace's own domain and `localpart@domain` is a member's email; otherwise nobody |
| Room with a member on another homeserver | A foreign audience: nothing internal is recalled into it |
| Direct room with a known member | That member's audience |
| Terminal turn | `PUT /rooms/{roomId}/send/m.room.message/ufo-{turn_id}` |

The transaction id is the turn's, so a retried delivery is the same transaction and the homeserver
answers it with the event it already sent. A turn whose whole answer is silence sends nothing. A
question is written out with numbered options; a connect or credential handoff, and a turn's shared
files, point at the workspace, since a room carries none of them.

The `/sync` position is stored per workspace in `matrix_ext_since`, a table the extension's
migration owns, after each batch is delivered. A restart resumes from it; a batch replayed after a
crash is admitted once, because each message's event id is its admission key. The first sync of a
stream only fixes where it stands — history from before the bot listened founds nothing.

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

With both slots filled, a member asks in chat to connect Matrix; `matrix_connect` asks the homeserver
whose token it holds and binds that MXID to the workspace. Invite the bot to a room from an account
on its own homeserver and it joins.

## Traps

- **An unlisted bot is bound but deaf.** The listener runs only the MXIDs `UFO_MATRIX_BOTS` names;
  binding one the deploy does not list admits nothing until it does.
- **Encrypted rooms are silent.** The surface reads unencrypted rooms only. In an encrypted room it
  hears nothing it can read, and admits nothing.
- **A new token is a new transaction scope.** Transaction ids are idempotent per access token, so a
  reply retried across a token rotation can land twice.
- **Invitations from other homeservers are left standing.** Only a user on the bot's own homeserver
  can bring it into a room.
- **A member outside the workspace's domain speaks as nobody.** The turn runs, with no member's
  memory and no member's authority.

## Tests

```bash
pytest extensions/matrix
```

`test_matrix_contracts.py` needs only `pytest`: the import gate, and which events may found a turn.
`test_matrix_surface.py` drives the listener and the post against a fake homeserver, and
`test_matrix_registry.py` loads the installed entry point through ufo's loader and applies the
migration; both skip where `ufo` is absent.

## License

Apache-2.0.
