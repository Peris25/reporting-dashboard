"""Store vehicle registration separately from legacy Solver IDs."""

from alembic import op
import sqlalchemy as sa

revision = "20260909_03"
down_revision = "20260904_02"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "reg_no" not in {column["name"] for column in inspector.get_columns("tickets")}:
        op.add_column("tickets", sa.Column("reg_no", sa.String(120), nullable=True))
    if "ix_tickets_reg_no" not in {index["name"] for index in inspector.get_indexes("tickets")}:
        op.create_index("ix_tickets_reg_no", "tickets", ["reg_no"])


def downgrade():
    op.drop_index("ix_tickets_reg_no", table_name="tickets")
    op.drop_column("tickets", "reg_no")
