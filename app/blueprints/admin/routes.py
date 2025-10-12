# app/blueprints/admin/routes.py
from flask import Blueprint, render_template, request, jsonify, url_for, redirect, flash
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models.user import User
from app.models.core import Student
# از مدل منتور اگر داری بعداً اضافه کن:
# from app.models.mentor import Mentor

bp = Blueprint("admin", __name__, url_prefix="/admin")


# فقط ادمین‌ها اجازهٔ ورود داشته باشند
@bp.before_request
@login_required
def ensure_admin():
    if (current_user.role or "").upper() != "ADMIN":
        flash("دسترسی مجاز نیست.", "error")
        return redirect(url_for("dashboard.index"))


# ---------- لیست کاربران ----------
@bp.get("/users")
def users_index():
    q = (request.args.get("q") or "").strip()
    base = User.query
    if q:
        like = f"%{q}%"
        base = base.filter(or_(User.username.like(like), User.email.like(like)))
    users = base.order_by(User.id.desc()).all()
    return render_template("admin/users/index.html", users=users, q=q)


# ---------- آپدیت username/password (AJAX) ----------
@bp.post("/users/<int:user_id>/update")
def users_update(user_id):
    u = User.query.get_or_404(user_id)

    payload = request.get_json(silent=True) or {}
    new_username = (payload.get("username") or "").strip()
    new_password = payload.get("password") or ""

    if new_username:
        exists = User.query.filter(User.id != u.id, User.username == new_username).first()
        if exists:
            return jsonify({"ok": False, "error": "username_taken"}), 409
        u.username = new_username

    if new_password:
        if len(new_password) < 6:
            return jsonify({"ok": False, "error": "weak_password"}), 400
        from werkzeug.security import generate_password_hash
        u.password_hash = generate_password_hash(new_password)

    db.session.commit()
    return jsonify({"ok": True})


# ---------- ساخت ادمین جدید (اختیاری) ----------
@bp.post("/users/create-admin")
def create_admin():
    if (current_user.role or "").upper() != "ADMIN":
        return jsonify({"ok": False, "error": "forbidden"}), 403

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email    = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not username or not email or len(password) < 6:
        return jsonify({"ok": False, "error": "invalid_input"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"ok": False, "error": "username_taken"}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({"ok": False, "error": "email_taken"}), 409

    from werkzeug.security import generate_password_hash
    u = User(username=username, email=email, role="ADMIN")
    u.password_hash = generate_password_hash(password)
    db.session.add(u)
    db.session.commit()
    return jsonify({"ok": True, "id": u.id}), 201


# ---------- رفتن به صفحه ویرایش پروفایل بر اساس نقش ----------
@bp.get("/users/<int:user_id>/edit-profile")
def route_to_profile_edit(user_id):
    u = User.query.get_or_404(user_id)
    role = (u.role or "").upper()

    if role == "STUDENT":
        # نگاشت ساده: دانشجو را با ایمیل کاربر پیدا کن
        s = Student.query.filter_by(email=u.email).first()
        if not s:
            flash("برای این کاربر، پروفایل دانشجو پیدا نشد.", "error")
            return redirect(url_for("admin.users_index"))
        return redirect(url_for("students.edit_form", student_id=s.id))

    elif role == "MENTOR":
        # اگر مدل منتور داری اینجا ریدایرکت کن
        flash("ویرایش منتور هنوز پیاده‌سازی نشده.", "info")
        return redirect(url_for("admin.users_index"))

    elif role == "ADMIN":
        flash("ادمین فقط اطلاعات حساب را می‌تواند ویرایش کند.", "info")
        return redirect(url_for("admin.users_index"))

    flash("نقش کاربر نامعتبر است.", "error")
    return redirect(url_for("admin.users_index"))
