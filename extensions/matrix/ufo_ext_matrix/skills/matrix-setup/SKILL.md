---
name: matrix-setup
description: "Load when an admin connects this workspace to Matrix, or when a connected bot hears nothing in its rooms. Not for setting up another chat surface, and not for sending a message into a room — a connected bot answers its rooms on its own."
metadata:
  depends: []
---
# Connect Matrix, in chat

Connecting is three things in order: the bot's own account on a homeserver, the two credential slots,
and the connect action on the `matrix` surface. None of it is a setting a member edits; each step is a
turn in this conversation.

## The bot needs an account of its own

The workspace's agent syncs as one Matrix user, and that user is the installation the surface routes
by. Register a fresh account for it on the homeserver and take that account's access token. An account
another bot or a person already syncs as is the one setup mistake with no visible symptom — both
readers receive the same stream, and each treats the other's messages as its own.

## Ask for the two slots, never for the token itself

| Slot | Holds |
| --- | --- |
| `matrix_homeserver` | The homeserver's base URL, e.g. `https://matrix.example.org` |
| `matrix_access_token` | The bot account's access token |

Call `request_credentials` for both. The admin fills them where the transcript cannot see them, so the
token is never typed into the conversation and never repeated back.

## Connect, and read what the homeserver says

With the slots filled, take the connect action on the `matrix` surface row. It asks the homeserver
whose token it holds and binds that MXID as the workspace's installation, so the bot the token belongs
to is the bot that gets bound and a wrong token is a refusal rather than a wrong binding. A second
token for the same bot replaces the binding; the listener reads the binding each sync round, so a
connect takes effect without a restart.

```
admin: connect our Matrix bot
agent: Connected @ufo:example.org. It is listening.
```

A bot another workspace already holds is refused by name: that MXID belongs elsewhere, and which
workspace holds it is not this workspace's to know. Register a separate account for this workspace's
agent and connect that one.

## Then invite it

A connected bot is in no rooms. A workspace member invites it to a room and it joins itself; an
invitation from anyone the workspace cannot resolve to a member is left standing. In a room it has
joined, the bot answers when it is mentioned, when the room holds only it and one other person, and
when a room it is already in conversation with wants it.

## Traps

Every trap here presents the same way — the agent does not answer — so read them in order rather than
reasoning back from the silence.

- **The deploy's pack does not bundle `matrix`.** A `[pack] name = "assistant"` in the deploy's
  configuration narrows the active set to that pack's own extensions, and `matrix` is not among them,
  so the surface never activates and no listener runs. A throwaway local pack listing the assistant
  set and `matrix` is the way through. A lockfile pinning the set reaches it only with `[pack] name`
  unset, because the pack narrows the active set after the lockfile has filled it.
- **The room is encrypted.** The listener reads an encrypted room's events as `m.room.encrypted`, with
  no body to hear, and founds nothing. Turn encryption off for that room, or use an unencrypted one.
- **Two readers share one account.** A token reused from another agent's bot makes both sync as the
  same user, and each reads the other's messages as its own. One account per workspace's agent.
- **The bot was never invited.** Joining a room is a member's act, not the bot's. A room nobody invited
  it to sends it nothing, and an invitation from someone the workspace cannot resolve to a member is
  left standing rather than refused.
