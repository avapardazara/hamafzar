from datetime import datetime
from app.extensions import db

class Skill(db.Model):
    __tablename__ = "skills"
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    # 'TECH' | 'SOFT'
    type = db.Column(db.String(10), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("name", "type", name="uq_skill_name_type"),
    )

class StudentSkill(db.Model):
    __tablename__ = "student_skills"
    id         = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id   = db.Column(db.Integer, db.ForeignKey("skills.id",   ondelete="CASCADE"), nullable=False, index=True)

    # فیلدهای اضافه مخصوص رکورد اتصال
    date_label = db.Column(db.String(32))    # مثلا '1403/07/18' یا تاریخ میلادی — فعلاً متنی
    hours      = db.Column(db.Integer)       # برای مهارت نرم
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    skill   = db.relationship("Skill")
