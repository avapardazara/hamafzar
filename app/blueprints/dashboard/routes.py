# app/blueprints/dashboard/routes.py
from datetime import date
from flask import Blueprint, render_template
from flask_login import login_required,current_user
from sqlalchemy import func
from app.extensions import db
from app.models.payment import Payment

bp = Blueprint("dashboard", __name__, url_prefix="/")

@bp.get("/")
@login_required
def index():
    print(f"User Role: {current_user.role}")
    # --- محاسبات KPI (نمونه؛ جایگزین با منطق خودتان اگر قبلاً نوشته‌اید)
    total_face = 0
    total_received = db.session.query(
        func.coalesce(func.sum(Payment.amount), 0.0)
    ).filter(Payment.kind == "tuition", Payment.status == "paid").scalar() or 0.0
    total_receivables = max(total_face - total_received, 0.0)
    overdue_count = 0  # اگر دارید از installments می‌خوانید این را محاسبه کنید

    # روند ماهانه دریافت‌ها (cash-basis)
    monthly_rows = (
        db.session.query(
            func.strftime("%Y-%m", Payment.paid_at).label("ym"),
            func.coalesce(func.sum(Payment.amount), 0.0),
        )
        .filter(Payment.kind == "tuition", Payment.status == "paid")
        .group_by("ym").order_by("ym")
        .all()
    )
    monthly = [{"ym": ym or "...", "amount": float(s or 0)} for ym, s in monthly_rows]
    monthly_max = max((m["amount"] for m in monthly), default=1.0)

    # ---- آبجکت‌های خروجی برای سازگاری قالب
    kpis = {
        "total_face": int(total_face),
        "total_received": int(total_received),
        "total_receivables": int(total_receivables),
        "overdue_count": int(overdue_count),
    }
    data = {
        "kpis": kpis,              # ← تا {{ data.kpis.* }} کار کند
        "monthly": monthly,        # ← اگر قالب از data.monthly استفاده کند
        "monthly_max": monthly_max,
    }

    return render_template(
        "dashboard/index.html",
        # دو مسیر موازی برای سازگاری با همه‌ی ارجاعات قالب
        data=data,
        kpis=kpis,
        monthly=monthly,
        monthly_max=monthly_max,
    )
