from __future__ import annotations
from datetime import date, timedelta, datetime
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import func
from app.extensions import db
from app.blueprints.installments import bp
from app.models.installment_plan import InstallmentPlan
from app.models.installment import Installment
from app.models.course import Course
from app.models.core import Student
from app.models.enrollment import Enrollment

def _safe_float(x, default=0.0):
    try:
        if x is None: return default
        return float(x)
    except Exception:
        return default

@bp.get("/")
@login_required
def index():
    plans = (InstallmentPlan.query
             .order_by(InstallmentPlan.id.desc())
             .all())
    # مجموع‌ها برای نمایش سریع
    rows = []
    for p in plans:
        n = len(p.installments or [])
        total = sum((i.amount_total or 0) for i in p.installments or [])
        paid = sum((i.amount_total or 0) for i in p.installments or [] if (i.status or "").upper()=="PAID")
        rows.append(dict(
            plan=p,
            count=n,
            total=int(total),
            paid=int(paid),
            remain=int(max(total - paid, 0))
        ))
    return render_template("installments/index.html", rows=rows)

@bp.get("/new")
@login_required
def create_form():
    courses = Course.query.order_by(Course.title.asc()).all()
    students = Student.query.order_by(Student.id.desc()).all()
    enrollments = Enrollment.query.order_by(Enrollment.id.desc()).all()
    return render_template("installments/create.html",
                           courses=courses, students=students, enrollments=enrollments)

@bp.post("/new")
@login_required
def create_submit():
    title = (request.form.get("title") or "").strip()
    course_id = request.form.get("course_id", type=int)
    student_id = request.form.get("student_id", type=int)
    enrollment_id = request.form.get("enrollment_id", type=int)

    total_amount = _safe_float(request.form.get("total_amount"), 0.0)
    count = max(int(request.form.get("installments_count", 1) or 1), 1)

    use_cheques = True if request.form.get("use_cheques") == "1" else False
    cheque_fee_percent = _safe_float(request.form.get("cheque_fee_percent"), 0.0)

    first_due_str = (request.form.get("first_due_date") or "").strip()
    first_due_date = None
    if first_due_str:
        try:
            first_due_date = datetime.strptime(first_due_str, "%Y-%m-%d").date()
        except Exception:
            first_due_date = None

    # محاسبه کارمزد
    cheque_fee_total = (total_amount * (cheque_fee_percent/100.0)) if use_cheques and cheque_fee_percent>0 else 0.0

    plan = InstallmentPlan(
        title=title or None,
        course_id=course_id,
        student_id=student_id,
        enrollment_id=enrollment_id,
        total_amount=total_amount,
        installments_count=count,
        use_cheques=use_cheques,
        cheque_fee_percent=cheque_fee_percent,
        cheque_fee_total=cheque_fee_total,
        first_due_date=first_due_date,
        status="OPEN",
    )
    db.session.add(plan)
    db.session.flush()  # تا id داشته باشد

    # تقسیم مساوی قسط‌ها
    base_share = total_amount / count
    fee_share = cheque_fee_total / count if cheque_fee_total>0 else 0.0

    # تولید اقساط با فاصله ماهانه
    due = first_due_date
    for i in range(1, count+1):
        # اگر تاریخ شروع نداد، از امروز/7 روز بعد فرضی:
        if not due:
            due = date.today() + timedelta(days=7*i)

        inst = Installment(
            plan_id=plan.id,
            seq=i,
            amount_base=base_share,
            cheque_fee_amount=fee_share,
            amount_total=base_share + fee_share,
            due_date=due,
            status="PENDING",
        )
        db.session.add(inst)
        # ماه بعد (تقریبی: +30 روز) یا می‌توان از منطق دقیق ماهانه بعداً استفاده کرد
        due = (due.replace(day=28) + timedelta(days=4)).replace(day=1)  # اول ماه بعد

    db.session.commit()
    flash("برنامه اقساط با موفقیت ایجاد شد.", "success")
    return redirect(url_for("installments.index"))

@bp.get("/<int:plan_id>")
@login_required
def details(plan_id: int):
    plan = InstallmentPlan.query.get_or_404(plan_id)
    insts = (Installment.query
             .filter(Installment.plan_id == plan.id)
             .order_by(Installment.seq.asc())
             .all())
    total = sum((i.amount_total or 0) for i in insts)
    paid = sum((i.amount_total or 0) for i in insts if (i.status or "").upper()=="PAID")
    remain = max(total - paid, 0)
    return render_template("installments/details.html",
                           plan=plan, installments=insts,
                           total=int(total), paid=int(paid), remain=int(remain))
