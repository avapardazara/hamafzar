"""sync models

Revision ID: 1b4195a63d70
Revises: 18f4f42923ce
Create Date: 2025-11-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from alembic import context

# این‌ها را با مقادیر فایل خودت هماهنگ کن
revision = '1b4195a63d70'
down_revision = '18f4f42923ce'
branch_labels = None
depends_on = None


def upgrade():
    # --- attendance ---
    # NOT NULL روی ستون موجود -> باید batch باشد
    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.alter_column(
            'timestamp',
            existing_type=sa.DateTime(),
            nullable=False
        )
        # اگر FK session_id تغییر کرده (حذف/افزودن)، اول حذف بعد ایجاد
        # Alembic اتومات نشون داده بود: removed FK و added FK
        # برای اطمینان: ابتدا drop اگر وجود دارد
        try:
            batch_op.drop_constraint('fk_attendance_session_id', type_='foreignkey')
        except Exception:
            pass
        batch_op.create_foreign_key(
            None,                 # نام اتومات
            'course_sessions',    # جدول مقصد
            local_cols=['session_id'],
            remote_cols=['id'],
            ondelete='CASCADE'    # اگر سقف نیاز داری، تنظیم کن
        )

    # --- course_sessions ---
    with op.batch_alter_table('course_sessions', schema=None) as batch_op:
        # ستون‌های جدید
        if not has_column('course_sessions', 'session_date'):
            batch_op.add_column(sa.Column('session_date', sa.Date(), nullable=True))
        if not has_column('course_sessions', 'start_time'):
            batch_op.add_column(sa.Column('start_time', sa.Time(), nullable=True))
        if not has_column('course_sessions', 'end_time'):
            batch_op.add_column(sa.Column('end_time', sa.Time(), nullable=True))

        # اگر ایندکس قدیمی وجود دارد حذف شود
        try:
            batch_op.drop_index('ix_course_sessions_date')
        except Exception:
            pass

        # NOT NULL روی ستون موجود 'date'
        batch_op.alter_column(
            'date',
            existing_type=sa.Date(),
            nullable=False
        )

        # اگر لازم داری ایندکس جدید بسازی، همینجا بساز:
        # batch_op.create_index('ix_course_sessions_session_date', ['session_date'])

    # --- session_files ---
    with op.batch_alter_table('session_files', schema=None) as batch_op:
        batch_op.alter_column(
            'uploaded_at',
            existing_type=sa.DateTime(),
            nullable=False
        )
        # FK session_id حذف/ایجاد
        try:
            batch_op.drop_constraint('fk_session_files_session_id', type_='foreignkey')
        except Exception:
            pass
        batch_op.create_foreign_key(
            None,
            'course_sessions',
            local_cols=['session_id'],
            remote_cols=['id'],
            ondelete='CASCADE'
        )


def downgrade():
    # برعکسِ بالا – برای dev می‌تونه اختیاری/ساده‌تر باشه
    with op.batch_alter_table('session_files', schema=None) as batch_op:
        # برگرداندن nullable
        batch_op.alter_column('uploaded_at', existing_type=sa.DateTime(), nullable=True)
        # FK را اگر لازم است drop کن (اختیاری)
        # try: batch_op.drop_constraint(...); except: pass

    with op.batch_alter_table('course_sessions', schema=None) as batch_op:
        batch_op.alter_column('date', existing_type=sa.Date(), nullable=True)
        # ایندکس جدید را اگر ساخته بودی drop کن
        # try: batch_op.drop_index('ix_course_sessions_session_date'); except: pass
        # ستون‌های جدید را حذف کن (اختیاری برای dev)
        try:
            batch_op.drop_column('end_time')
        except Exception:
            pass
        try:
            batch_op.drop_column('start_time')
        except Exception:
            pass
        try:
            batch_op.drop_column('session_date')
        except Exception:
            pass

    with op.batch_alter_table('attendance', schema=None) as batch_op:
        batch_op.alter_column('timestamp', existing_type=sa.DateTime(), nullable=True)
        # FK را اگر لازم است به حالت قبلی برگردانی (اختیاری)
        # try: batch_op.drop_constraint(...); except: pass


# Helper: ساده برای تشخیص وجود ستون (در sqlite ممکن است مفید باشد)


def has_column(table_name, column_name):
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c['name'] for c in insp.get_columns(table_name)]
    return column_name in cols
