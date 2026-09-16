"""Create ticket and activity tables."""

from alembic import op

from reporting.database import Base

revision = "20260904_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
