# -*- coding: utf-8 -*-
# مدل سبک برای نگه‌داری توکن‌های هش‌شده
from datetime import datetime
from app.extensions import db

class ApiToken(db.Model):
    __tablename__ = "api_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)  # نام جدول User شما ممکن است متفاوت باشد
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)  # sha256 hex
    label = db.Column(db.String(120))
    scope = db.Column(db.String(120))  # در صورت نیاز: مثلا "read:finance,write:installments"
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("api_tokens", lazy="dynamic"))

    def is_active(self) -> bool:
        if self.revoked_at:
            return False
        if self.expires_at and self.expires_at <= datetime.utcnow():
            return False
        return True
