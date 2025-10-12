from datetime import datetime
from app.extensions import db

class Mentor(db.Model):
    __tablename__ = "mentors"
    id         = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(120))
    last_name  = db.Column(db.String(120))
    email      = db.Column(db.String(200), unique=True, index=True)
    phone      = db.Column(db.String(50))
    expertise  = db.Column(db.String(200))
    avatar     = db.Column(db.String(255))  # ← مسیر فایل/نام فایل عکس
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def full_name(self):
        fn = (self.first_name or "").strip()
        ln = (self.last_name or "").strip()
        return (fn + " " + ln).strip() or "—"
