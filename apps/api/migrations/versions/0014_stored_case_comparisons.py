"""Save operator comparison snapshots independently of transient scan uploads."""

import sqlalchemy as sa
from alembic import op

revision = "0014_stored_case_comparisons"
down_revision = "0013_unknown_rights_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # create_all adoption may already have installed the additive column.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("review_cases")}
    if "archive_record" not in columns:
        op.add_column("review_cases", sa.Column("archive_record", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("review_cases") as batch:
        batch.drop_column("archive_record")
