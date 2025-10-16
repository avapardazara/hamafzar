"""add Enrollment table

Revision ID: 43d2d018820e
Revises: 3c08efa92c86
Create Date: 2025-10-14 14:xx:xx
"""
from alembic import op
import sqlalchemy as sa

revision = "43d2d018820e"
down_revision = "3c08efa92c86"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # اگر اجرای قبلی نیمه‌کاره بود
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_attendances")

    if "enrollments" not in insp.get_table_names():
        op.create_table(
            "enrollments",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("student_id", sa.Integer, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
            sa.Column("joined_at", sa.DateTime, nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
            sa.UniqueConstraint("student_id", "course_id", name="uq_student_course"),
        )
    else:
        # اگر جدول هست، مطمئن شو یونیک کانسترینت رو دارد؛ اگر نه، بسازش
        uqs = [uc["name"] for uc in insp.get_unique_constraints("enrollments")]
        if "uq_student_course" not in uqs:
            op.create_unique_constraint("uq_student_course", "enrollments", ["student_id", "course_id"])

def downgrade():
    # اگر لازم است فقط وقتی جدول واقعاً وجود دارد حذف شود
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "enrollments" in insp.get_table_names():
        op.drop_table("enrollments")
