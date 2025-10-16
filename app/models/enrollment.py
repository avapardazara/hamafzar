from datetime import datetime
from app.extensions import db

class Enrollment(db.Model):
    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE | CANCELLED
    joined_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # روابط
    student = db.relationship("Student", backref=db.backref("enrollments", cascade="all, delete-orphan"))
    course  = db.relationship("Course",  backref=db.backref("enrollments", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("student_id", "course_id", name="uq_student_course"),
    )

    def __repr__(self):
        return f"<Enrollment student={self.student_id} course={self.course_id}>"
