from datetime import datetime
from sqlalchemy import func
from sqlalchemy.ext.hybrid import hybrid_property
from app.extensions import db

class CourseSession(db.Model):
    __tablename__ = "course_sessions"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey("mentors.id", ondelete="SET NULL"), nullable=True, index=True)
    topic = db.Column(db.String(200), nullable=False, default="جلسه")
    description = db.Column(db.Text)
    
    # تغییرات جدید: تاریخ و زمان جداگانه
    date = db.Column(db.DateTime, nullable=False)  # تاریخ و زمان کامل برای ذخیره 
    session_date = db.Column(db.Date, nullable=False)  # تاریخ جلسه بدون ساعت
    start_time   = db.Column(db.Time, nullable=True)   # زمان شروع جلسه
    end_time     = db.Column(db.Time, nullable=True) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    course = db.relationship("Course", backref=db.backref("sessions", cascade="all, delete-orphan"))
    files = db.relationship("SessionFile", back_populates="session", cascade="all, delete-orphan")
    attendances = db.relationship("Attendance", back_populates="session", cascade="all, delete-orphan")

    # برای سازگاری با کدهای قدیمی
    @property
    def attendees(self):
        return self.attendances

    # --- Hybrid Properties: تاریخ و ساعت ---
    @hybrid_property
    def session_date_full(self):
        """این ترکیب تاریخ و زمان برای UI یا فیلتر استفاده میشه."""
        return datetime.combine(self.session_date, self.start_time) if self.session_date and self.start_time else None

    @session_date_full.expression
    def session_date_full(cls):
        return func.concat(func.date(cls.session_date), " ", func.time(cls.start_time))

    @hybrid_property
    def room(self):
        """اگر ستون room اضافه شد، می‌تواند به آن متصل شود."""
        return ""

    # هنگام ایجاد رکورد جدید، تاریخ و زمان را به‌طور صحیح تنظیم کنید
    @classmethod
    def create(cls, course_id, mentor_id, topic, description, date, start_time):
        session_date = date.date()  # تاریخ بدون ساعت
        new_session = cls(
            course_id=course_id,
            mentor_id=mentor_id,
            topic=topic,
            description=description,
            date=date,
            session_date=session_date,  # تنظیم تاریخ بدون ساعت
            start_time=start_time,  # زمان شروع جلسه
            created_at=datetime.utcnow()
        )
        return new_session

class SessionFile(db.Model):
    __tablename__ = "session_files"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("course_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    session = db.relationship("CourseSession", back_populates="files")

class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("course_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False)  # PRESENT | ABSENT | LATE | REMOTE | ...
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    session = db.relationship("CourseSession", back_populates="attendances")
    student = db.relationship("Student", backref=db.backref("attendances", cascade="all, delete-orphan"))
