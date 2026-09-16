"""Add Solver and Office Team support intake fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260904_02"
down_revision = "20260904_01"
branch_labels = None
depends_on = None


def upgrade():
    fields = [
        ("support_request_number", sa.String(40)), ("requester_type", sa.String(40)),
        ("requester_name", sa.String(200)), ("job_request_id", sa.String(120)),
        ("solver_id", sa.String(120)), ("office_department", sa.String(120)),
        ("received_by", sa.String(200)), ("call_outcome", sa.String(50)),
        ("callback_required", sa.String(10)), ("callback_deadline", sa.String(40)),
        ("callback_completed_at", sa.String(40)), ("resolution_summary", sa.Text()),
    ]
    bind = op.get_bind()
    existing_columns = {column["name"] for column in inspect(bind).get_columns("tickets")}
    for name, column_type in fields:
        if name not in existing_columns:
            op.add_column("tickets", sa.Column(name, column_type, nullable=True))
    existing_indexes = {index["name"] for index in inspect(bind).get_indexes("tickets")}
    if "ix_tickets_support_request_number" not in existing_indexes:
        op.create_index("ix_tickets_support_request_number", "tickets", ["support_request_number"], unique=True)
    for name in ["requester_type", "requester_name", "job_request_id", "solver_id", "received_by", "callback_required"]:
        if f"ix_tickets_{name}" not in existing_indexes:
            op.create_index(f"ix_tickets_{name}", "tickets", [name])


def downgrade():
    for name in ["requester_type", "requester_name", "job_request_id", "solver_id", "received_by", "callback_required"]:
        op.drop_index(f"ix_tickets_{name}", table_name="tickets")
    op.drop_index("ix_tickets_support_request_number", table_name="tickets")
    for name in ["resolution_summary", "callback_completed_at", "callback_deadline", "callback_required", "call_outcome", "received_by", "office_department", "solver_id", "job_request_id", "requester_name", "requester_type", "support_request_number"]:
        op.drop_column("tickets", name)
