from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user, login_required
from ...extensions import db
from ...models.user import User

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
        (User.username==username) | (User.email==username) | (User.phone_number==username)
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
