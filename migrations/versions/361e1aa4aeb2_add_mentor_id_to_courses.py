"""add mentor_id to courses"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "361e1aa4aeb2"
down_revision = "527c329c0fda"  # همونی که قبلش بوده
branch_labels = None
depends_on = None


def upgrade() -> None:
    # در SQLite بهتره داخل batch کار کنیم
    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mentor_id", sa.Integer(), nullable=True))
        # اسم کانسترینت الزامی‌ست
        batch_op.create_foreign_key(
            "fk_courses_mentor_id_mentors",   # << اسم الزامی
            "mentors",                        # جدول رفرنس
            ["mentor_id"],                    # ستون‌های لوکال
            ["id"],                           # ستون‌های ریموت
        )


def downgrade() -> None:
    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.drop_constraint("fk_courses_mentor_id_mentors", type_="foreignkey")
        batch_op.drop_column("mentor_id")
