"""add description to courses"""

from alembic import op
import sqlalchemy as sa

# Alembic identifiers
revision = "ed2a789fbec8"
down_revision = "f93a8dabe45f"
branch_labels = None
depends_on = None


def _has_column(table_name: str, col_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table_name)]
    return col_name in cols


def upgrade():
    # فقط اگر ستون وجود ندارد، اضافه کن
    if not _has_column("courses", "description"):
        with op.batch_alter_table("courses") as batch_op:
            batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))


def downgrade():
    # فقط اگر ستون وجود دارد، حذف کن
    if _has_column("courses", "description"):
        with op.batch_alter_table("courses") as batch_op:
            batch_op.drop_column("description")
