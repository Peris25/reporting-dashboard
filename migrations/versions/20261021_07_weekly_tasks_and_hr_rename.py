"""Add weekly_tasks table and rename the HR department to 'HR and Admin'."""
from alembic import op
import sqlalchemy as sa

revision = "20261021_07"
down_revision = "20260916_06"
branch_labels = None
depends_on = None

_OLD, _NEW = "HR", "HR and Admin"


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # Rename the department on existing rows so nothing falls out of view.
    renames = [
        ("users", "department"),
        ("tickets", "assigned_department"),
        ("tickets", "reporting_department"),
        ("draft_requests", "suggested_department"),
    ]
    for table, column in renames:
        if table in tables and column in {c["name"] for c in inspector.get_columns(table)}:
            op.execute(
                sa.text(f"UPDATE {table} SET {column} = :new WHERE {column} = :old")
                .bindparams(new=_NEW, old=_OLD)
            )

    if "weekly_tasks" not in tables:
        op.create_table(
            "weekly_tasks",
            sa.Column("task_id", sa.String(36), primary_key=True),
            sa.Column("source_key", sa.String(160), nullable=False),
            sa.Column("kpi_area", sa.String(100), nullable=True),
            sa.Column("department", sa.String(60), nullable=True),
            sa.Column("subteam", sa.String(60), nullable=True),
            sa.Column("week_label", sa.String(80), nullable=True),
            sa.Column("week_start", sa.String(20), nullable=True),
            sa.Column("week_end", sa.String(20), nullable=True),
            sa.Column("due_at", sa.String(20), nullable=True),
            sa.Column("task", sa.Text(), nullable=False, server_default=""),
            sa.Column("comments", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="Yet to Start"),
            sa.Column("created_at", sa.String(40), nullable=False, server_default=""),
            sa.Column("updated_at", sa.String(40), nullable=False, server_default=""),
        )
        op.create_index("ix_weekly_tasks_source_key", "weekly_tasks", ["source_key"], unique=True)
        op.create_index("ix_weekly_tasks_department", "weekly_tasks", ["department"])
        op.create_index("ix_weekly_tasks_week_start", "weekly_tasks", ["week_start"])
        op.create_index("ix_weekly_tasks_status", "weekly_tasks", ["status"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "weekly_tasks" in tables:
        for index in ("ix_weekly_tasks_status", "ix_weekly_tasks_week_start",
                      "ix_weekly_tasks_department", "ix_weekly_tasks_source_key"):
            op.drop_index(index, table_name="weekly_tasks")
        op.drop_table("weekly_tasks")
    renames = [
        ("users", "department"),
        ("tickets", "assigned_department"),
        ("tickets", "reporting_department"),
        ("draft_requests", "suggested_department"),
    ]
    for table, column in renames:
        if table in tables and column in {c["name"] for c in inspector.get_columns(table)}:
            op.execute(
                sa.text(f"UPDATE {table} SET {column} = :old WHERE {column} = :new")
                .bindparams(new=_NEW, old=_OLD)
            )
