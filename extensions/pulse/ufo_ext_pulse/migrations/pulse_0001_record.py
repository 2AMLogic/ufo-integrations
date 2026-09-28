"""pulse's tables: the historical record a brief series builds, one row at a time.

Both are append-only in meaning and upsert in mechanism. The natural key is what a second write of
the same fact would carry, so a retried fire, a crash replay, or a gather that surfaces one lead
twice in a run lands one row rather than a duplicate — which a surrogate key would have let through
and which the file this record projects to could never have caught.
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


def downgrade() -> None:
    op.drop_table("pulse_ext_covered")
    op.drop_table("pulse_ext_sighting")
