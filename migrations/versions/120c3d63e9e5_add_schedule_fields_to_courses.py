"""add schedule fields to courses

Revision ID: 120c3d63e9e5
Revises: 9133ab35c22f
Create Date: 2025-10-13 17:20:16.739795

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '120c3d63e9e5'
down_revision = '9133ab35c22f'
branch_labels = None
depends_on = None


def _colset():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("courses")}


def upgrade():
    cols = _colset()

    def add(name, type_, **kw):
        if name not in cols:
            op.add_column("courses", sa.Column(name, type_, **kw))

    # زمان‌بندی و کاور
    add("schedule_type", sa.String(16), nullable=True)
    add("schedule_days", sa.String(32), nullable=True)
    add("schedule_pattern", sa.String(32), nullable=True)
    add("start_date", sa.String(10), nullable=True)   # ذخیره شمسی/میلادی به‌صورت متن
    add("end_date", sa.String(10), nullable=True)
    add("cover_path", sa.String(255), nullable=True)

    # شهریه/اقساط/سهم منتور
    add("tuition_per_student", sa.Integer(), nullable=True)
    add("installment_enabled", sa.Boolean(), nullable=True)
    add("installment_count", sa.Integer(), nullable=True)
    add("mentor_share_percent", sa.Float(), nullable=True)


def downgrade():
    # در SQLite drop_column امن است
    for name in [
        "mentor_share_percent",
        "installment_count",
        "installment_enabled",
        "tuition_per_student",
        "cover_path",
        "end_date",
        "start_date",
        "schedule_pattern",
        "schedule_days",
        "schedule_type",
    ]:
        try:
            op.drop_column("courses", name)
        except Exception:
            # اگر ستونی وجود نداشت، ساکت رد شو
            pass
