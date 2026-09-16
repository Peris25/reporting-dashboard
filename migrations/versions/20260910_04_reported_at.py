"""Separate actual reporting time from dashboard entry time."""
from alembic import op
import sqlalchemy as sa

revision = "20260910_04"
down_revision = "20260909_03"
branch_labels = None
depends_on = None


def upgrade():
    if "reported_at" not in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tickets")}:
        op.add_column("tickets", sa.Column("reported_at", sa.String(40), nullable=True))


def downgrade():
    op.drop_column("tickets", "reported_at")
