"""abcd_fix_courses_installment_flag

Revision ID: 487a782bcff4
Revises: f85ea6c40cb3
Create Date: 2025-10-29 09:55:56.565237

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '487a782bcff4'
down_revision = 'f85ea6c40cb3'
branch_labels = None
depends_on = None


def _has_column(bind, table_name, col_name):
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table_name)]
    return col_name in cols


def upgrade():
    bind = op.get_bind()

    # courses.installment_enabled (Bool)
    if not _has_column(bind, "courses", "installment_enabled"):
        op.add_column(
            "courses",
            sa.Column("installment_enabled", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        )

    # courses.installment_count (Int) — تعداد اقساط تعریف‌شده برای این دوره
    if not _has_column(bind, "courses", "installment_count"):
        op.add_column(
            "courses",
            sa.Column("installment_count", sa.Integer(), nullable=True),
        )

    # courses.default_inst_count (Int) — پیش‌فرض تعداد اقساط
    if not _has_column(bind, "courses", "default_inst_count"):
        op.add_column(
            "courses",
            sa.Column("default_inst_count", sa.Integer(), nullable=True),
        )

    # courses.default_use_cheques (Bool) — پیش‌فرض دریافت چک
    if not _has_column(bind, "courses", "default_use_cheques"):
        op.add_column(
            "courses",
            sa.Column("default_use_cheques", sa.Boolean(), nullable=True, server_default=sa.text("0")),
        )

    # courses.default_cheque_fee_percent (Float) — درصد کارمزد چک پیش‌فرض
    if not _has_column(bind, "courses", "default_cheque_fee_percent"):
        op.add_column(
            "courses",
            sa.Column("default_cheque_fee_percent", sa.Float(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()

    if _has_column(bind, "courses", "default_cheque_fee_percent"):
        op.drop_column("courses", "default_cheque_fee_percent")

    if _has_column(bind, "courses", "default_use_cheques"):
        op.drop_column("courses", "default_use_cheques")

    if _has_column(bind, "courses", "default_inst_count"):
        op.drop_column("courses", "default_inst_count")

    if _has_column(bind, "courses", "installment_count"):
        op.drop_column("courses", "installment_count")

    if _has_column(bind, "courses", "installment_enabled"):
        op.drop_column("courses", "installment_enabled")
