from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c48b8a3c761e"
down_revision = "4f265e612e3d"  # همان که قبلش اجرا شد
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        # دور زدن batch_alter_table: اضافه‌کردن ستون با SQL خام
        op.execute(
            "ALTER TABLE payments ADD COLUMN created_at DATETIME NOT NULL DEFAULT (CURRENT_TIMESTAMP)"
        )
        # ایندکس ممکن است از قبل ساخته شده باشد؛ ایمن بساز
        try:
            op.create_index("ix_payments_created_at", "payments", ["created_at"], unique=False)
        except Exception:
            pass
    else:
        # مسیر استاندارد برای سایر DBها
        op.add_column(
            "payments",
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        try:
            op.create_index("ix_payments_created_at", "payments", ["created_at"], unique=False)
        except Exception:
            pass
        # تمیزکاری سرور‌دیفالت
        try:
            op.alter_column("payments", "created_at", server_default=None)
        except Exception:
            pass


def downgrade():
    # ایمن: حذف ایندکس اگر بود
    try:
        op.drop_index("ix_payments_created_at", table_name="payments")
    except Exception:
        pass

    # در SQLite حذف ستون دردسر دارد؛ عمداً نادیده می‌گیریم (no-op).
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        try:
            op.drop_column("payments", "created_at")
        except Exception:
            pass
