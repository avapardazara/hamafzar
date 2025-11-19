from flask import Blueprint, render_template, request, redirect, url_for, flash, make_response
from flask_login import login_user, logout_user, current_user, login_required
from ...extensions import db
from ...models.user import User
from sqlalchemy import or_
from werkzeug.security import check_password_hash
from flask import jsonify
from flask_cors import cross_origin
from flask_jwt_extended import create_access_token, set_access_cookies
bp = Blueprint("auth", __name__, url_prefix="/auth")

@bp.get("/login")
def login_form():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("auth/login.html")

@bp.post("/login")
def login():
    username = request.form.get("username","").strip()
    password = request.form.get("password","").strip()
    remember = bool(request.form.get("remember"))

    if not username or not password:
        flash("نام کاربری و رمز عبور الزامی است.", "error")
        return redirect(url_for("auth.login_form"))

    user = User.query.filter(
        (User.username==username) | (User.email==username) | (User.phone_number ==username)
    ).first()

    if not user or not user.check_password(password):
        flash("نام کاربری یا رمز عبور نادرست است.", "error")
        return redirect(url_for("auth.login_form"))

    if not user.is_active:
        flash("حساب کاربری شما غیرفعال است.", "error")
        return redirect(url_for("auth.login_form"))

    login_user(user, remember=remember)
    flash("خوش آمدی ✨", "success")
    return redirect(url_for("dashboard.index"))

@bp.get("/logout")
@login_required
def logout():
    logout_user()
    flash("با موفقیت خارج شدی.", "info")
    return redirect(url_for("auth.login_form"))

@bp.post("/login")
def login_post():
    identity = (request.form.get("username") or "").strip()  # username یا email
    password = request.form.get("password") or ""
    user = User.query.filter(or_(User.username == identity, User.email == identity)).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
        flash("نام کاربری/ایمیل یا رمز عبور نادرست است.", "error")
        return redirect(url_for("auth.login_form"))
    login_user(user, remember=True)
    return redirect(url_for("dashboard.index"))
# --- ورود از طریق JSON برای فرانت‌اند Vue --- #
@bp.route("/api/login", methods=["POST", "OPTIONS"])
@cross_origin(
    origins="http://localhost:3000",
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)
def api_login():
    # 🟡 اگر مرورگر preflight (OPTIONS) فرستاد، اینجا جواب می‌دیم
    if request.method == "OPTIONS":
        # Flask-CORS خودش هدرها رو اضافه می‌کنه
        return make_response("", 204)

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"message": "نام کاربری و رمز عبور الزامی است."}), 400

    # مطابق مدل خودت، می‌تونی فیلد phone_number یا email رو هم اضافه کنی
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"message": "نام کاربری یا رمز عبور اشتباه است."}), 401

    # ساخت JWT
    access_token = create_access_token(identity=str(user.id))
    resp = jsonify({
        "message": "ورود موفق",
        "access_token": access_token,
        "user": {
            "id": user.id,
            "username": user.username,
            "phone_number": getattr(user, "phone_number", None),
        }
    })
    # ست‌کردن کوکی (اگر در پروژه‌ات استفاده می‌کنی)
    set_access_cookies(resp, access_token)

    return resp

@bp.post("/api/logout")
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True}), 200
