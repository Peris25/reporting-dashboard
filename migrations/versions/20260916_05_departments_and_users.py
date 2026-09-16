"""Add department routing fields and a users table for role-based access."""
from alembic import op
import sqlalchemy as sa

revision = "20260916_05"
down_revision = "20260910_04"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    ticket_columns = {column["name"] for column in inspector.get_columns("tickets")}
    for column in ("assigned_department", "assigned_subteam", "reporting_department"):
        if column not in ticket_columns:
            op.add_column("tickets", sa.Column(column, sa.String(60), nullable=True))
    # Existing requests predate departments. The dashboard was IT-only, so route
    # them to IT and keep them visible to the IT global view.
    op.execute("UPDATE tickets SET assigned_department = 'IT' WHERE assigned_department IS NULL OR assigned_department = ''")

    if "users" not in set(inspector.get_table_names()):
        op.create_table(
            "users",
            sa.Column("username", sa.String(120), primary_key=True),
            sa.Column("display_name", sa.String(200), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("department", sa.String(60), nullable=False),
            sa.Column("subteam", sa.String(60), nullable=True),
            sa.Column("role", sa.String(20), nullable=False, server_default="member"),
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.String(40), nullable=False, server_default=""),
            sa.Column("updated_at", sa.String(40), nullable=False, server_default=""),
        )
        op.create_index("ix_users_department", "users", ["department"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "users" in set(inspector.get_table_names()):
        op.drop_index("ix_users_department", table_name="users")
        op.drop_table("users")
    ticket_columns = {column["name"] for column in inspector.get_columns("tickets")}
    for column in ("reporting_department", "assigned_subteam", "assigned_department"):
        if column in ticket_columns:
            op.drop_column("tickets", column)
