# -*- coding: utf-8 -*-
# Helperهای تولید/هش/اعتبارسنجی توکن و دکوراتور احراز هویت API
import secrets, hashlib, hmac
from functools import wraps
from datetime import datetime
from flask import request, jsonify, g
from app.extensions import db
from app.models.api_token import ApiToken

# هش استاندارد (SHA-256 hex)
def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

# تولید توکن و ذخیره هش‌شده
def create_api_token(user, label=None, scope=None, expires_at=None):
    token_plain = secrets.token_urlsafe(32)  # نمایش به کاربر فقط یک‌بار
    token_h = hash_token(token_plain)
    obj = ApiToken(user_id=user.id, token_hash=token_h, label=label, scope=scope, expires_at=expires_at)
    db.session.add(obj)
    db.session.commit()
    return token_plain, obj

# از هدرها توکن خام را بیرون بکش
def _read_token_from_headers():
    # Authorization: Bearer <token>
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    # یا X-Auth-Token
    x = request.headers.get("X-Auth-Token")
    if x: return x.strip()
    return None

# اعتبارسنجی توکن و ست‌کردن g.api_user / g.api_token
def authenticate_request_or_none():
    token_raw = _read_token_from_headers()
    if not token_raw:
        return None
    token_h = hash_token(token_raw)
    tok = ApiToken.query.filter_by(token_hash=token_h).first()
    if not tok or not tok.is_active():
        return None
    tok.last_used_at = datetime.utcnow()
    db.session.commit()
    g.api_user = tok.user
    g.api_token = tok
    return tok.user

def api_auth_required(roles=None):
    """
    دکوراتور برای محافظت از endpointهای API.
    roles: لیست نقش‌های مجاز (مثلا ['admin','superadmin'] یا ['mentor','admin','superadmin'])
    """
    roles = roles or []
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = authenticate_request_or_none()
            if not user:
                return jsonify({"error": "unauthorized"}), 401
            if roles and not user_has_any_role(user, roles):
                return jsonify({"error": "forbidden"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# مقایسه امن هش‌ها
def safe_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")

# === RBAC ===
# تلاش می‌کنیم نقش را از مدل موجود برداریم (role یا roles)
def get_user_roles(user):
    # اولویت: user.role (رشته) → سپس user.roles (کالکشن)
    if hasattr(user, "role") and isinstance(user.role, str):
        return {user.role.lower()}
    if hasattr(user, "roles"):
        # فرض: آبجکت‌هایی با name یا رشته ساده
        items = []
        for r in getattr(user, "roles") or []:
            name = getattr(r, "name", None)
            items.append((name or str(r)).lower())
        return set(items)
    return set()

def user_has_any_role(user, allowed):
    uroles = get_user_roles(user)
    allowed = {r.lower() for r in allowed}
    return bool(uroles & allowed)
