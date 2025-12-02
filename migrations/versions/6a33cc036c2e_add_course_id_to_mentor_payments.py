"""add course_id to mentor_payments

Revision ID: 6a33cc036c2e
Revises: e4a84c28f0e0
Create Date: 2025-11-29 15:18:51.098537
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6a33cc036c2e"
down_revision = "e4a84c28f0e0"
branch_labels = None
depends_on = None


def upgrade():
    # چون SQLite هستیم بهتره از batch_alter_table استفاده کنیم
    with op.batch_alter_table("mentor_payments") as batch:
        batch.add_column(sa.Column("course_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_mentor_payments_course_id",  # اسم FK
            "courses",                       # جدول مقصد
            ["course_id"],                   # ستون‌های این جدول
            ["id"],                          # ستون‌های جدول مقصد
        )


def downgrade():
    with op.batch_alter_table("mentor_payments") as batch:
        batch.drop_constraint(
            "fk_mentor_payments_course_id", type_="foreignkey"
        )
        batch.drop_column("course_id")
