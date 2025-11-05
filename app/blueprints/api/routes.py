# -*- coding: utf-8 -*-
# Endpointهای نمونه: سلامت و پروفایل فعلی
from flask import jsonify, g
from . import api_bp
from app.security.tokens import api_auth_required

@api_bp.route("/api/health", methods=["GET"])
def api_health():
    # بدون نیاز به توکن – برای تست Proxy/اتصال
    return jsonify({"ok": True, "service": "ham-afzar-api"})

@api_bp.route("/api/me", methods=["GET"])
@api_auth_required()  # هر نقش تایید شود
def api_me():
    u = getattr(g, "api_user", None)
    # خروجی مینیمال برای فرانت
    if not u:
        return jsonify({"error": "unauthorized"}), 401
    # تلاش برای نقش واحد/لیست
    role = getattr(u, "role", None)
    if not role and hasattr(u, "roles"):
        # اگر آرایه‌ای از نقش‌ها دارید:
        try:
            role = next(iter([getattr(r, "name", str(r)) for r in u.roles]), None)
        except Exception:
            role = None
    return jsonify({
        "id": getattr(u, "id", None),
        "name": getattr(u, "name", None) or getattr(u, "full_name", None),
        "email": getattr(u, "email", None),
        "role": (role or "student")
    })
