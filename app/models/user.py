from datetime import datetime
from werkzeug.security import check_password_hash as wz_check
from flask_login import UserMixin
from ..extensions import db, login_manager
from flask_bcrypt import Bcrypt


bcrypt = Bcrypt()
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
    role          = db.Column(db.String(30), default="admin", index=True)  # ساده: admin, MENTOR, STUDENT, FINANCE
    is_active     = db.Column(db.Boolean, default=True, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password: str):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, raw: str) -> bool:
        ph = (self.password_hash or "").strip()

        # اگر هش، bcrypt استاندارد است ($2a$ / $2b$ / $2y$)
        if ph.startswith("$2a$") or ph.startswith("$2b$") or ph.startswith("$2y$"):
            try:
                return bcrypt.check_password_hash(ph, raw)
            except Exception:
                return False  # هرچیزی غیرمنتظره: لاگین نامعتبر

        # تلاش برای پشتیبانی از هش‌های legacy (Werkzeug PBKDF2)
        try:
            return wz_check(ph, raw)
        except Exception:
            # نه bcrypt است نه werkzeug؛ پسورد نامعتبر تلقی شود
            return False

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }

    @property
    def is_admin(self) -> bool:
        # مرجع: اگر نقش دقیقا admin (case-insensitive) بود
        return (self.role or "").lower() == "admin"
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
