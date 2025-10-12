from datetime import datetime
from ..extensions import db

class Student(db.Model):
    __tablename__ = "students"
    id            = db.Column(db.Integer, primary_key=True)
    first_name    = db.Column(db.String(80), nullable=False)
    last_name     = db.Column(db.String(80), nullable=False)
    national_code = db.Column(db.String(20), unique=True, index=True)
    phone         = db.Column(db.String(20), unique=False, index=True)
    email         = db.Column(db.String(120))
    address       = db.Column(db.String(255))
    notes         = db.Column(db.Text)
    avatar_path   = db.Column(db.String(255))
    is_deleted    = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
