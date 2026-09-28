"""pulse's tables: the historical record a brief series builds, one row at a time.

**Why a table.** The record used to be a JSON Lines file at a workspace-relative path, which
resolves against the working directory the turn's carrier happens to start in — the deploy home for
an attended CLI run, the conversation's sandbox root for a scheduled fire. So one series accumulated
one ledger per carrier, and neither knew about the other. Measured on the demo deploy: the
`agent-runtimes` series had two `covered.jsonl` files, 15 rows each, and for edition 2026-09-28 they
shared **no story at all** — six rows in each, zero overlap. Both were plausible, and the no-repeat
rule was enforced against whichever half the running carrier could see.

A row keyed by `(workspace_id, series, ...)` is reachable identically from every turn in the
workspace, whatever carrier ran it and whatever directory it started in. That is the property the
file lacked and the whole reason these exist.

The sighting and covered keys are natural rather than surrogate: the key is what a second write of
the same fact would carry, so a retried fire, a crash replay, or a gather that surfaces one lead
twice lands one row rather than a duplicate. That also makes importing an old file safe to repeat,
which is how a deploy carrying divergent ledgers merges them.

`pulse_ext_series` is the third table and a different kind: not record but bookkeeping. It names the
conversation a series lives in and how far the workspace-file projection has caught up, so the
projection job opens a sandbox only for a series whose record has actually advanced.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "pulse_0001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = ("pulse",)
depends_on: str | None = "20260927025054"


def upgrade() -> None:
    op.create_table(
        "pulse_ext_sighting",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("series", sa.Text(), nullable=False),
        sa.Column("seen", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        # One lead seen once on one day at one address is one sighting. The url is in the key
        # because a story that moves address between sightings is a different row to reconcile,
        # which is the question `reconcile` exists to ask and this must not answer for it.
        sa.PrimaryKeyConstraint("workspace_id", "series", "seen", "slug", "url"),
    )
    op.create_table(
        "pulse_ext_covered",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("series", sa.Text(), nullable=False),
        sa.Column("edition", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        # One row per story per edition, exactly as the ledger has always meant it: a slug carried
        # again under the material-new-development exception is a row in each edition that carried
        # it, and one edition cannot carry a story twice.
        sa.PrimaryKeyConstraint("workspace_id", "series", "edition", "slug"),
    )


    op.create_table(
        "pulse_ext_series",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("series", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # Null until the first projection lands. A series whose `updated_at` is newer than this has
        # rows the workspace file does not carry yet, and that comparison is the whole of what the
        # projection job selects on: a job that woke for every series would open a container per
        # conversation per tick to rewrite files nothing had changed.
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "series"),
    )


def downgrade() -> None:
    op.drop_table("pulse_ext_series")
    op.drop_table("pulse_ext_covered")
    op.drop_table("pulse_ext_sighting")
