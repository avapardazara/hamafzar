from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e3bf82039890"          # همانی که در فایل خودت هست
down_revision = "43d2d018820e"     # همانی که در فایل خودت هست
branch_labels = None
depends_on = None

def upgrade():
    # فقط ستون joined_at را به enrollments اضافه می‌کنیم — بدون دستکاری payments
    op.add_column(
        "enrollments",
        sa.Column("joined_at", sa.DateTime(), nullable=True)
    )

def downgrade():
    # در SQLite حذف ستون ساده نیست؛ برای dev نیازی به rollback واقعی نداریم.
    # اگر لازم شد بعداً یک مایگریشن reconstruct بنویسیم.
    pass
