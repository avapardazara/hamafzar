"""extend Course: scheduling + finance + cover

Revision ID: f93a8dabe45f
Revises: 0e91d0a7169e
Create Date: 2025-10-13 14:04:44.827699
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f93a8dabe45f'
down_revision = '0e91d0a7169e'
branch_labels = None
depends_on = None


def upgrade():
    # روی SQLite: فقط تغییر nullable و ساخت ایندکس‌ها
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.alter_column(
            'title',
            existing_type=sa.VARCHAR(length=200),
            nullable=True
        )
        batch_op.create_index('ix_payments_kind', ['kind'], unique=False)
        batch_op.create_index('ix_payments_mentor_id', ['mentor_id'], unique=False)
    # نکته: تغییر/حذف/ایجاد FK ها در SQLite دردسرسازه؛
    # در این مایگریشن بهشون دست نمی‌زنیم.


def downgrade():
    # برگرداندن تغییرات ایندکس و nullable
    with op.batch_alter_table('payments', schema=None) as batch_op:
        batch_op.drop_index('ix_payments_mentor_id')
        batch_op.drop_index('ix_payments_kind')
        batch_op.alter_column(
            'title',
            existing_type=sa.VARCHAR(length=200),
            nullable=False
        )
    # هیچ تغییری روی FK ها اعمال نکردیم که لازم باشه برگردونیم.
