from alembic import op
import sqlalchemy as sa

revision = "cd72bdce3e2a"
down_revision = "f93a8dabe45f"   # یا پِرِنت واقعی
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        # اگر قبلاً description اضافه نشده، این خط را هم نگه دارید؛
        # اگر اضافه‌اش کرده‌اید، این خط را حذف کنید.
        # batch_op.add_column(sa.Column('description', sa.Text(), nullable=True))

        batch_op.add_column(sa.Column('start_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('end_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('cover_path', sa.String(length=255), nullable=True))

def downgrade():
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('cover_path')
        batch_op.drop_column('end_date')
        batch_op.drop_column('start_date')
        # اگر بالا description را اضافه کرده‌اید، این‌جا هم پاکش کنید:
        # batch_op.drop_column('description')
