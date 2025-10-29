"""add installments & cheques tables

Revision ID: a1b2c3d4e5f6
Revises: <آخرین Revision فعلی شما را اینجا بگذارید>
Create Date: 2025-10-29 10:00:00
"""
from alembic import op
import sqlalchemy as sa


# ❶ شناسه‌ها
revision = "0929cc6f0213"   # ← از نام فایل خودش استفاده می‌کنیم
down_revision = "2406d6757b66"  # ← آخرین هدِ موجود پروژه‌ت قبل از این سه فایل
branch_labels = None
depends_on = None


def upgrade():
    # جدول اقساط
    op.create_table(
        'installments',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('course_id', sa.Integer, sa.ForeignKey('courses.id'), nullable=False, index=True),
        sa.Column('student_id', sa.Integer, sa.ForeignKey('students.id'), nullable=True, index=True),
        sa.Column('enrollment_id', sa.Integer, sa.ForeignKey('enrollments.id'), nullable=True, index=True),

        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('amount', sa.Float, nullable=False, default=0.0),
        sa.Column('due_date', sa.Date, nullable=False),

        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),   # PENDING/PAID/CANCELLED
        sa.Column('method', sa.String(20), nullable=True),                              # CASH/CARD/TRANSFER/CHEQUE

        sa.Column('surcharge_percent', sa.Float, nullable=True),
        sa.Column('surcharge_amount', sa.Float, nullable=True),

        sa.Column('paid_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # جدول چک‌های هر قسط (اختیاری)
    op.create_table(
        'cheques',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('installment_id', sa.Integer, sa.ForeignKey('installments.id'), nullable=False, index=True),

        sa.Column('cheque_number', sa.String(100), nullable=True),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('issuer_name', sa.String(100), nullable=True),

        sa.Column('issue_date', sa.Date, nullable=True),
        sa.Column('due_date', sa.Date, nullable=True),
        sa.Column('amount', sa.Float, nullable=True),

        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),  # PENDING/CLEARED/BOUNCED
        sa.Column('note', sa.Text, nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table('cheques')
    op.drop_table('installments')
