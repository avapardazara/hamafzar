"""add description to courses"""

from alembic import op
import sqlalchemy as sa

# Alembic identifiers
revision = "ed2a789fbec8"
down_revision = "f93a8dabe45f"
branch_labels = None
depends_on = None


def _has_column(table, colname):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == colname for c in insp.get_columns(table))

def upgrade():
    if not _has_column("courses", "description"):
        with op.batch_alter_table("courses") as batch_op:
            batch_op.add_column(sa.Column("description", sa.Text()))

def downgrade():
    # اگر لازم داری قابل برگشت باشد:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if any(c["name"] == "description" for c in insp.get_columns("courses")):
        with op.batch_alter_table("courses") as batch_op:
            batch_op.drop_column("description")
