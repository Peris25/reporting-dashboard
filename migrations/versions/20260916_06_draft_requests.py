"""Add a draft_requests table for staged (pending-approval) intake."""
from alembic import op
import sqlalchemy as sa

revision = "20260916_06"
down_revision = "20260916_05"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "draft_requests" not in set(inspector.get_table_names()):
        op.create_table(
            "draft_requests",
            sa.Column("draft_id", sa.String(36), primary_key=True),
            sa.Column("source", sa.String(40), nullable=False, server_default="whatsapp"),
            sa.Column("source_reference", sa.String(255), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(100), nullable=True),
            sa.Column("priority", sa.String(30), nullable=True),
            sa.Column("suggested_department", sa.String(60), nullable=True),
            sa.Column("suggested_subteam", sa.String(60), nullable=True),
            sa.Column("requester_name", sa.String(200), nullable=True),
            sa.Column("contact", sa.String(60), nullable=True),
            sa.Column("reported_at", sa.String(40), nullable=True),
            sa.Column("excerpt", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(40), nullable=False, server_default=""),
            sa.Column("reviewed_at", sa.String(40), nullable=True),
            sa.Column("reviewed_by", sa.String(200), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("approved_ticket_id", sa.String(36), nullable=True),
            sa.Column("source_fingerprint", sa.String(64), nullable=True),
        )
        op.create_index("ix_draft_requests_status", "draft_requests", ["status"])
        op.create_index("ix_draft_requests_source_fingerprint", "draft_requests", ["source_fingerprint"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "draft_requests" in set(inspector.get_table_names()):
        op.drop_index("ix_draft_requests_source_fingerprint", table_name="draft_requests")
        op.drop_index("ix_draft_requests_status", table_name="draft_requests")
        op.drop_table("draft_requests")
