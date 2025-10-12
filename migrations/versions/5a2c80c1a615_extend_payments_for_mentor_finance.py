"""extend payments for mentor finance"""
from alembic import op
import sqlalchemy as sa

# این‌ها را Alembic خودش تولید می‌کند؛ نگه‌دار
revision = 'extend_payments_for_mentor_finance'
down_revision = None  # اگر قبلاً ریویژنی داری، همون رو بگذار
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    def has_col(table, col):
        return any(c["name"] == col for c in insp.get_columns(table))

    # جدول ممکنه قبلاً نباشه (Dev تازه)؛ اگر نبود، بسازیمش کامل
    if "payments" not in insp.get_table_names():
        op.create_table(
            "payments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("student_id", sa.Integer(), nullable=True, index=True),
            sa.Column("mentor_id", sa.Integer(), nullable=True, index=True),
            sa.Column("type", sa.String(length=8), nullable=False, server_default="IN"),
            sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("kind", sa.String(length=10), nullable=False, server_default="INCOME"),
            sa.Column("status", sa.String(length=20), nullable=True),
            sa.Column("paid_at", sa.DateTime(), nullable=True),
            sa.Column("note", sa.String(length=255), nullable=True),
        )
        return

    # اگر جدول موجود است، کمبودها را اضافه کن (بدون شکستن داده فعلی)
    with op.batch_alter_table("payments") as batch:
        if not has_col("payments", "mentor_id"):
            batch.add_column(sa.Column("mentor_id", sa.Integer(), nullable=True))
        if not has_col("payments", "kind"):
            batch.add_column(sa.Column("kind", sa.String(length=10), nullable=False, server_default="INCOME"))
        if not has_col("payments", "status"):
            batch.add_column(sa.Column("status", sa.String(length=20), nullable=True))
        if not has_col("payments", "paid_at"):
            batch.add_column(sa.Column("paid_at", sa.DateTime(), nullable=True))
        if not has_col("payments", "note"):
            batch.add_column(sa.Column("note", sa.String(length=255), nullable=True))

        # student_id در داده‌های دانشجو هست؛ مطمئن شو nullable است
        if has_col("payments", "student_id"):
            batch.alter_column("student_id", existing_type=sa.Integer(), nullable=True)

        # type ممکنه بدون server_default تعریف شده باشد
        if has_col("payments", "type"):
            batch.alter_column("type", existing_type=sa.String(length=8), nullable=False, server_default="IN")

def downgrade():
    # برای سادگی، چیزی را حذف نمی‌کنیم (backward-safe)
    pass
