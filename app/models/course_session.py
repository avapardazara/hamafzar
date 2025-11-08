from app.extensions import db
from datetime import datetime

class CourseSession(db.Model):
    __tablename__ = "course_sessions"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey("mentors.id", ondelete="SET NULL"), nullable=True, index=True)
    topic = db.Column(db.String(200), nullable=False, default="جلسه")
    description = db.Column(db.Text)
    date = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    course = db.relationship("Course", backref=db.backref("sessions", cascade="all, delete-orphan"))
    files = db.relationship("SessionFile", back_populates="session", cascade="all, delete-orphan")
    attendees = db.relationship("Attendance", back_populates="session", cascade="all, delete-orphan")
    attendances = db.relationship("Attendance", back_populates="session", cascade="all, delete-orphan")

class SessionFile(db.Model):
    __tablename__ = "session_files"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("course_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    session = db.relationship("CourseSession", back_populates="files")

class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer,
    db.ForeignKey("course_sessions.id", ondelete="CASCADE"),
    nullable=False, index=True)
    student_id = db.Column(db.Integer, nullable=False)
    student_id = db.Column(db.Integer,
                          db.ForeignKey("students.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False)  # PRESENT | ABSENT | LATE
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    session = db.relationship("CourseSession", back_populates="attendees")
    student = db.relationship("Student")
    session = db.relationship("CourseSession", back_populates="attendances")
    student = db.relationship("Student",
    backref=db.backref("attendances", cascade="all, delete-orphan"))
