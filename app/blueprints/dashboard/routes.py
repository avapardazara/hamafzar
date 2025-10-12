from flask import Blueprint, render_template
from flask_login import login_required, current_user
from flask import redirect, url_for


bp = Blueprint("dashboard", __name__)

@bp.route("/")
def home_redirect():
    return redirect(url_for("auth.login_form"))

@bp.route("/dashboard")
@login_required
def index():
    # KPIهای نمونه؛ بعداً از سرویس‌های مالی و کورس پر می‌کنیم
    data = {
        "role": current_user.role,
        "kpis": [
            {"label": "درآمد کل (ماه جاری)", "value": "۰", "hint": "ریال"},
            {"label": "وصول‌نشده", "value": "۰", "hint": "ریال"},
            {"label": "هزینه منتورها", "value": "۰", "hint": "ریال"},
        ],
        "upcoming": [
            # بعداً از CourseSession پر می‌کنیم
        ]
    }
    return render_template("dashboard/index.html", data=data)
