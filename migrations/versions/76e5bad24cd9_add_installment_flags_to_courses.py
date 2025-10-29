"""add installment-related columns to courses

Revision ID: a1b2c3d4e5f6
Revises: <PUT_YOUR_CURRENT_HEAD_HERE>
Create Date: 2025-10-29 09:30:00
"""
from alembic import op
import sqlalchemy as sa

# -- این دو مقدار را مطابق فایل خودت تنظیم کن:
revision = "76e5bad24cd9"
down_revision = "0929cc6f0213"  # ← دقیقاً بعد از فایل شماره 1 بیاید
branch_labels = None
depends_on = None


def upgrade():
    # برای سازگاری با SQLite از batch_alter_table استفاده می‌کنیم
    with op.batch_alter_table('courses') as batch:
        # آیا ستون‌ها قبلا وجود ندارند؟ در SQLite چک مستقیم سخت است،
        # ولی اضافه کردن به صورت idempotent را با try/except انجام نمی‌دهیم؛
        # فرض پاک: ستون‌ها وجود ندارند.
        batch.add_column(sa.Column('allow_installments', sa.Boolean(), nullable=True, server_default='0'))
        batch.add_column(sa.Column('installment_enabled', sa.Boolean(), nullable=True, server_default='0'))
        batch.add_column(sa.Column('installment_count', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('default_inst_count', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('default_use_cheques', sa.Boolean(), nullable=True, server_default='0'))
        batch.add_column(sa.Column('default_cheque_fee_percent', sa.Float(), nullable=True))

    # بعد از ساخت، server_default های بولین را پاک می‌کنیم تا فقط مقدار واقعی ثبت شود
    with op.batch_alter_table('courses') as batch:
        batch.alter_column('allow_installments', server_default=None)
        batch.alter_column('installment_enabled', server_default=None)
        batch.alter_column('default_use_cheques', server_default=None)


def downgrade():
    with op.batch_alter_table('courses') as batch:
        batch.drop_column('default_cheque_fee_percent')
        batch.drop_column('default_use_cheques')
        batch.drop_column('default_inst_count')
        batch.drop_column('installment_count')
        batch.drop_column('installment_enabled')
        batch.drop_column('allow_installments')


