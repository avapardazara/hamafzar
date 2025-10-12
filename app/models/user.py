from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from ..extensions import db, login_manager

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)

    # می‌تونی هر کدوم رو که خواستی پر کنی، برای لاگین فقط username و password لازم داریم
    first_name    = db.Column(db.String(80))
    last_name     = db.Column(db.String(80))
    phone_number  = db.Column(db.String(20), unique=True)
    email         = db.Column(db.String(120), unique=True)
    username      = db.Column(db.String(120), unique=True, index=True, nullable=False)

    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(30), default="ADMIN", index=True)  # ساده: ADMIN, MENTOR, STUDENT, FINANCE
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, raw: str):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
