from datetime import datetime
from app.extensions import db

class Course(db.Model):
    __tablename__ = "courses"
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(200), nullable=False, index=True)
    mentor_name = db.Column(db.String(120))          # فعلاً ساده؛ بعداً به Mentor FK وصل می‌کنیم
    status      = db.Column(db.String(20), default="ACTIVE")  # ACTIVE/ARCHIVED
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class Enrollment(db.Model):
    __tablename__ = "enrollments"
    id          = db.Column(db.Integer, primary_key=True)
    student_id  = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id   = db.Column(db.Integer, db.ForeignKey("courses.id",  ondelete="CASCADE"), nullable=False, index=True)
    status      = db.Column(db.String(20), default="ONGOING")  # ONGOING / DONE / DROPPED
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    course = db.relationship("Course")
