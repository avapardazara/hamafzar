from datetime import datetime
from app.extensions import db

class MentorSkill(db.Model):
    __tablename__ = "mentor_skills"

    id         = db.Column(db.Integer, primary_key=True)
    mentor_id  = db.Column(db.Integer, db.ForeignKey("mentors.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id   = db.Column(db.Integer, db.ForeignKey("skills.id",   ondelete="CASCADE"), nullable=False, index=True)

    # فیلدهای اضافه (عین دانشجو)
    date_label = db.Column(db.String(32))     # مثلا '1403/07/18'
    hours      = db.Column(db.Integer)        # برای مهارت نرم
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    skill   = db.relationship("Skill")