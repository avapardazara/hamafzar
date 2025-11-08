"""add sessions to courses

Revision ID: 18f4f42923ce
Revises: 98e51c0fc927
Create Date: 2025-11-08 08:44:03.960273
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "18f4f42923ce"
down_revision = "98e51c0fc927"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # تمیزکاریِ باقیمانده‌های شکست قبلی (در SQLite امن است)
    op.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_course_sessions"))
    op.execute(sa.text("DROP TABLE IF EXISTS attendances"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_attendances_session_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_attendances_student_id"))

    # --- جدول‌های جدید: attendance و session_files (ایمن نسبت به وجود قبلی) ---
    tables = set(insp.get_table_names())

    if "attendance" not in tables:
        op.create_table(
            "attendance",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=True),
            sa.Column("student_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["course_sessions.id"],
                name="fk_attendance_session_id_course_sessions",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["student_id"],
                ["students.id"],
                name="fk_attendance_student_id_students",
                ondelete="CASCADE",
            ),
        )
        op.create_index(
            "ix_attendance_session_id", "attendance", ["session_id"], unique=False
        )
        op.create_index(
            "ix_attendance_student_id", "attendance", ["student_id"], unique=False
        )

    if "session_files" not in tables:
        op.create_table(
            "session_files",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("file_path", sa.String(length=255), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["course_sessions.id"],
                name="fk_session_files_session_id_course_sessions",
                ondelete="CASCADE",
            ),
        )

    # --- تغییرات course_sessions به‌صورت مقاوم ---
    cols = {c["name"] for c in insp.get_columns("course_sessions")}
    idxs = {ix["name"] for ix in insp.get_indexes("course_sessions")}

    # اگر ایندکس قدیمی روی session_date وجود دارد، حذفش کن (فقط برای DBهای قدیمی)
    if "ix_course_sessions_session_date" in idxs:
        op.drop_index("ix_course_sessions_session_date", table_name="course_sessions")

    with op.batch_alter_table("course_sessions") as batch:
        # فیلدهای جدید
        if "mentor_id" not in cols:
            batch.add_column(sa.Column("mentor_id", sa.Integer(), nullable=True))
        if "topic" not in cols:
            batch.add_column(sa.Column("topic", sa.String(length=200), nullable=True))
        if "description" not in cols:
            batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        if "date" not in cols:
            # در SQLite نباید DEFAULT غیرثابت بدهیم؛ خالی می‌سازیم و بعداً پر می‌کنیم
            batch.add_column(sa.Column("date", sa.DateTime(), nullable=True))

        # ستون‌های قدیمی را اگر بودند حذف کن
        for old in ("session_date", "start_time", "end_time", "room", "note"):
            if old in cols:
                batch.drop_column(old)

    # ایندکس‌های جدید (اگر نبودند)
    idxs = {ix["name"] for ix in insp.get_indexes("course_sessions")}
    if "ix_course_sessions_date" not in idxs and "date" in {c["name"] for c in insp.get_columns("course_sessions")}:
        op.create_index("ix_course_sessions_date", "course_sessions", ["date"], unique=False)
    if "ix_course_sessions_mentor_id" not in idxs and "mentor_id" in {c["name"] for c in insp.get_columns("course_sessions")}:
        op.create_index("ix_course_sessions_mentor_id", "course_sessions", ["mentor_id"], unique=False)

    # FK mentor_id → mentors.id (اگر هنوز تعریف نشده)
    # SQLite مستقیماً چک FK ندارد؛ این فراخوانی چندباره harmless است.
    with op.batch_alter_table("course_sessions") as batch:
        batch.create_foreign_key(
            "fk_course_sessions_mentor_id_mentors",
            "mentors",
            ["mentor_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # بک‌فیل امن برای DBهای قدیمی (در DB تازه دیتایی وجود ندارد)
    course_cols = {c["name"] for c in insp.get_columns("course_sessions")}
    if "topic" in course_cols:
        op.execute(sa.text("UPDATE course_sessions SET topic = COALESCE(topic, 'جلسه')"))
    if "date" in course_cols:
        if "created_at" in course_cols:
            op.execute(sa.text("UPDATE course_sessions SET date = COALESCE(date, created_at)"))
        else:
            op.execute(sa.text("UPDATE course_sessions SET date = COALESCE(date, CURRENT_TIMESTAMP)"))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # حذف FK و ایندکس‌های جدید
    with op.batch_alter_table("course_sessions") as batch:
        try:
            batch.drop_constraint("fk_course_sessions_mentor_id_mentors", type_="foreignkey")
        except Exception:
            pass

    for ix in ("ix_course_sessions_date", "ix_course_sessions_mentor_id"):
        try:
            op.drop_index(ix, table_name="course_sessions")
        except Exception:
            pass

    # بازگردانی ستون‌ها (حداقلی)
    with op.batch_alter_table("course_sessions") as batch:
        for col in ("date", "description", "topic", "mentor_id"):
            try:
                batch.drop_column(col)
            except Exception:
                pass
        # ستون‌های قدیمی را فقط اگر لازم شد برگردان (اختیاری)
        # batch.add_column(sa.Column("session_date", sa.Date(), nullable=False))
        # batch.add_column(sa.Column("start_time", sa.Time(), nullable=True))
        # batch.add_column(sa.Column("end_time", sa.Time(), nullable=True))
        # batch.add_column(sa.Column("room", sa.String(length=120), nullable=True))
        # batch.add_column(sa.Column("note", sa.Text(), nullable=True))

    # حذف جدول‌های جدید
    for t in ("session_files", "attendance"):
        try:
            op.drop_table(t)
        except Exception:
            pass
