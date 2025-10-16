"""course sessions + attendance

Revision ID: 3c08efa92c86
Revises: 120c3d63e9e5
Create Date: 2025-10-13 15:xx:xx.xxxxxx
"""
from alembic import op
import sqlalchemy as sa

revision = "3c08efa92c86"
down_revision = "120c3d63e9e5"
branch_labels = None
depends_on = None


def _table_exists(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _index_exists(insp, table: str, name: str) -> bool:
    try:
        return any(ix.get("name") == name for ix in insp.get_indexes(table))
    except Exception:
        # بعضی درایورها ممکنه get_indexes نداشته باشند
        return False


def upgrade():
    # اگر اجرای قبلی نصفه مانده بود، جدول موقتی Alembic را پاک کن (SQLite)
    op.execute("DROP TABLE IF EXISTS _alembic_tmp_courses")

    bind = op.get_bind()
    insp = sa.inspect(bind)

    # ---------- course_sessions ----------
    if not _table_exists(insp, "course_sessions"):
        op.create_table(
            "course_sessions",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_date", sa.Date, nullable=False),
            sa.Column("start_time", sa.Time),
            sa.Column("end_time", sa.Time),
            sa.Column("room", sa.String(120)),
            sa.Column("note", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    # ایندکس‌ها را فقط اگر نیستند بساز
    if not _index_exists(insp, "course_sessions", "ix_course_sessions_course_id"):
        op.create_index("ix_course_sessions_course_id", "course_sessions", ["course_id"])
    if not _index_exists(insp, "course_sessions", "ix_course_sessions_session_date"):
        op.create_index("ix_course_sessions_session_date", "course_sessions", ["session_date"])

    # ---------- attendances ----------
    if not _table_exists(insp, "attendances"):
        op.create_table(
            "attendances",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("session_id", sa.Integer, sa.ForeignKey("course_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("student_id", sa.Integer, sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="PRESENT"),  # PRESENT | ABSENT | LATE
            sa.Column("note", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("session_id", "student_id", name="uq_attend_session_student"),
        )

    if not _index_exists(insp, "attendances", "ix_attendances_session_id"):
        op.create_index("ix_attendances_session_id", "attendances", ["session_id"])
    if not _index_exists(insp, "attendances", "ix_attendances_student_id"):
        op.create_index("ix_attendances_student_id", "attendances", ["student_id"])

    # ---------- تغییر نوع mentor_share_percent به Integer (SQLite-safe) ----------
    cols = [c["name"] for c in insp.get_columns("courses")]
    if "mentor_share_percent_int" not in cols and "mentor_share_percent" in cols:
        with op.batch_alter_table("courses") as b:
            b.add_column(sa.Column("mentor_share_percent_int", sa.Integer(), nullable=True))

        op.execute("""
            UPDATE courses
            SET mentor_share_percent_int = CAST(COALESCE(mentor_share_percent, 0) AS INTEGER)
        """)

        with op.batch_alter_table("courses") as b:
            b.drop_column("mentor_share_percent")
            b.alter_column(
                "mentor_share_percent_int",
                new_column_name="mentor_share_percent",
                existing_type=sa.Integer(),
                nullable=True,
            )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # برگرداندن mentor_share_percent به FLOAT (اگر الان Integer است)
    cols = [c["name"] for c in insp.get_columns("courses")]
    if "mentor_share_percent" in cols:
        with op.batch_alter_table("courses") as b:
            b.add_column(sa.Column("mentor_share_percent_float", sa.Float(), nullable=True))

        op.execute("""
            UPDATE courses
            SET mentor_share_percent_float = CAST(COALESCE(mentor_share_percent, 0) AS FLOAT)
        """)

        with op.batch_alter_table("courses") as b:
            b.drop_column("mentor_share_percent")
            b.alter_column(
                "mentor_share_percent_float",
                new_column_name="mentor_share_percent",
                existing_type=sa.Float(),
                nullable=True,
            )

    # ایندکس‌ها و جدول‌های attendance
    if _index_exists(insp, "attendances", "ix_attendances_student_id"):
        op.drop_index("ix_attendances_student_id", table_name="attendances")
    if _index_exists(insp, "attendances", "ix_attendances_session_id"):
        op.drop_index("ix_attendances_session_id", table_name="attendances")
    if _table_exists(insp, "attendances"):
        op.drop_table("attendances")

    # ایندکس‌ها و جدول‌های course_sessions
    if _index_exists(insp, "course_sessions", "ix_course_sessions_session_date"):
        op.drop_index("ix_course_sessions_session_date", table_name="course_sessions")
    if _index_exists(insp, "course_sessions", "ix_course_sessions_course_id"):
        op.drop_index("ix_course_sessions_course_id", table_name="course_sessions")
    if _table_exists(insp, "course_sessions"):
        op.drop_table("course_sessions")
