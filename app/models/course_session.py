from datetime import datetime

from sqlalchemy import func
from sqlalchemy.ext.hybrid import hybrid_property

from app.extensions import db


class CourseSession(db.Model):
    __tablename__ = "course_sessions"

    id = db.Column(db.Integer, primary_key=True)

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    mentor_id = db.Column(
        db.Integer,
        db.ForeignKey("mentors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    topic = db.Column(db.String(200), nullable=False, default="جلسه")
    description = db.Column(db.Text)

    # زمان برگزاری جلسه (تاریخ + ساعت)
    date = db.Column(db.DateTime, nullable=False)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # روابط
    course = db.relationship(
        "Course",
        backref=db.backref("sessions", cascade="all, delete-orphan"),
    )

    files = db.relationship(
        "SessionFile",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    attendances = db.relationship(
        "Attendance",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    # برای سازگاری عقب‌رو: بعضی جاها ممکنه از attendees استفاده کرده باشن
    @property
    def attendees(self):
        return self.attendances

    # --- Hybrid Properties: تاریخ و ساعت ---

    @hybrid_property
    def session_date(self):
        """تاریخ (بدون ساعت) برای فیلتر و UI."""
        return self.date.date() if self.date else None

    @session_date.expression
    def session_date(cls):
        return func.date(cls.date)

    @hybrid_property
    def start_time(self):
        """ساعت شروع بر اساس فیلد date فعلی."""
        return self.date.time() if self.date else None

    @start_time.expression
    def start_time(cls):
        return func.time(cls.date)

    @hybrid_property
    def end_time(self):
        """
        Compatibility shim:
        فعلاً همان start_time را برمی‌گرداند.
        اگر بعداً ستون end_datetime/duration اضافه شد، اینجا آپدیت می‌شود.
        """
        return self.date.time() if self.date else None

    @end_time.expression
    def end_time(cls):
        return func.time(cls.date)

    @hybrid_property
    def room(self):
        """
        Compatibility shim:
        الان ستون room نداریم، برای جلوگیری از خطا رشته خالی برمی‌گردانیم.
        اگر بعداً location/room اضافه شد، این متد به آن متصل می‌شود.
        """
        return ""


class SessionFile(db.Model):
    __tablename__ = "session_files"

    id = db.Column(db.Integer, primary_key=True)

    session_id = db.Column(
        db.Integer,
        db.ForeignKey("course_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    file_path = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))

    uploaded_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    session = db.relationship("CourseSession", back_populates="files")


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)

    session_id = db.Column(
        db.Integer,
        db.ForeignKey("course_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    student_id = db.Column(
        db.Integer,
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # PRESENT | ABSENT | LATE | REMOTE | ...
    status = db.Column(db.String(50), nullable=False)

    timestamp = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    # روابط
    session = db.relationship(
        "CourseSession",
        back_populates="attendances",
    )

    student = db.relationship(
        "Student",
        backref=db.backref(
            "attendances",
            cascade="all, delete-orphan",
        ),
    )
