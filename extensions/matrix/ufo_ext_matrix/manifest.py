"""What the matrix extension declares: one durable surface, the two credential slots its bot needs,
the setup action that binds that bot to a workspace, and the skill that walks an admin through it.

A Matrix room is a conversation and the people in it are members. The bot user's `/sync` stream is
the surface's listener, and each terminal turn is one message back into its room, sent under a
transaction id derived from the turn so a retried delivery lands once. The deploy names the bots
its listener runs in `UFO_MATRIX_BOTS`; each workspace holds its own bot's homeserver and token, and
`matrix_connect` binds the bot the token belongs to.

Setup happens in chat and nowhere else. `matrix_connect` is an instance action bound to the `matrix`
surface, so it is offered on that one surface row — `action:surface:matrix_connect` — rather than as a
tool a turn holds everywhere, and `matrix-setup` is the skill that carries the order of the steps and
the four silences a misconfigured bot answers with.

The surface reads unencrypted rooms. An encrypted event, an edit, and a redaction found no turn."""

from pathlib import Path

from ufo.sdk.manifest import CredentialSlot, Manifest, SkillSpec
from ufo.sdk.objects import SURFACE_KIND
from ufo.sdk.surfaces import SurfaceSpec
from ufo.sdk.tools import ObjectBinding, ToolDef
from ufo_ext_matrix.events import SURFACE
from ufo_ext_matrix.surface import (
    BOTS_ENV,
    HOMESERVER_SLOT,
    TOKEN_SLOT,
    ConnectInput,
    MatrixSurface,
    refuse_requests,
)

NAME = "matrix"
VERSION = "0.1.0"
CONNECT_TOOL = "matrix_connect"

SKILLS_ROOT = Path(__file__).parent / "skills"
SKILL_NAMES = ("matrix-setup",)


def manifest(surface: MatrixSurface | None = None) -> Manifest:
    matrix = surface or MatrixSurface()
    return Manifest(
        name=NAME,
        version=VERSION,
        surfaces=(
            SurfaceSpec(
                name=SURFACE,
                identify=refuse_requests,
                listen=matrix.listen,
                post=matrix.post,
            ),
        ),
        credentials=(
            CredentialSlot(
                name=HOMESERVER_SLOT,
                description="Base URL of the homeserver the Matrix bot user lives on.",
            ),
            CredentialSlot(
                name=TOKEN_SLOT,
                description="Access token of the Matrix bot user.",
            ),
        ),
        tools=(
            ToolDef(
                name=CONNECT_TOOL,
                description=(
                    "Connect this workspace's Matrix bot: check its access token with the "
                    "homeserver and bind the bot so its rooms reach this workspace."
                ),
                input_model=ConnectInput,
                handler=matrix.connect,
                side_effecting=True,
                bound=ObjectBinding(kind=SURFACE_KIND, binding="instance", name=SURFACE),
            ),
        ),
        skills=tuple(SkillSpec(path=SKILLS_ROOT / name) for name in SKILL_NAMES),
        deploy_keys=(BOTS_ENV,),
    )
