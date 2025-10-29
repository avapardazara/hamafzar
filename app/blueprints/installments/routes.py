from __future__ import annotations
from datetime import date, timedelta, datetime
from flask import request, redirect, url_for, flash, render_template
from flask_login import login_required
from sqlalchemy import func

from app.extensions import db
from app.blueprints.installments import bp
from app.models.course import Course
from app.models.installment import InstallmentPlan, Installment
from app.models.payment import Payment

# ساخت الگوی اقساط برای یک دوره بر اساس تنظیمات پیش‌فرض Course
@bp.post("/course/<int:course_id>/create-template")
@login_required
def create_course_template(course_id: int):
    c = Course.query.get_or_404(course_id)
    if not c.allow_installments:
        flash("این دوره اقساطی نیست.", "warning")
        return redirect(url_for("courses.edit", course_id=course_id))

    exists = InstallmentPlan.query.filter_by(course_id=c.id, student_id=None, enrollment_id=None).first()
    if exists:
        flash("الگوی اقساط قبلاً ساخته شده است.", "info")
        return redirect(url_for("courses.edit", course_id=course_id))

    total_amount = float(getattr(c, "tuition_per_student", 0) or 0.0)
    n = max(int(c.default_inst_count or 1), 1)
    use_cheques = bool(c.default_use_cheques)
    fee_pct = float(c.default_cheque_fee_percent or 0.0)
    fee_total = total_amount * (fee_pct / 100.0) if (use_cheques and fee_pct > 0) else 0.0

    plan = InstallmentPlan(
        title=f"الگوی اقساط دوره #{c.id}",
        course_id=c.id,
        total_amount=total_amount,
        installments_count=n,
        use_cheques=use_cheques,
        cheque_fee_percent=fee_pct,
        cheque_fee_total=fee_total,
        first_due_date=date.today() + timedelta(days=7),
        status="OPEN",
    )
    db.session.add(plan); db.session.flush()

    base_share = total_amount / n
    fee_share = (fee_total / n) if fee_total > 0 else 0.0
    due = plan.first_due_date
    for i in range(1, n + 1):
        db.session.add(Installment(
            plan_id=plan.id,
            seq=i,
            amount_base=base_share,
            cheque_fee_amount=fee_share,
            amount_total=base_share + fee_share,
            due_date=due,
            status="PENDING",
        ))
        # ماه بعد
        due = (due.replace(day=28) + timedelta(days=4)).replace(day=1)

    db.session.commit()
    flash("الگوی اقساط دوره ساخته شد.", "success")
    return redirect(url_for("courses.edit", course_id=course_id))


# افزودن یک قسط جدید به الگوی دوره (فرم ساده در تب)
@bp.post("/plan/<int:plan_id>/add-installment")
@login_required
def add_installment(plan_id: int):
    plan = InstallmentPlan.query.get_or_404(plan_id)
    seq = (plan.installments.order_by(Installment.seq.desc()).first().seq + 1) if plan.installments.count() else 1
    amount_base = request.form.get("amount_base", type=float) or 0.0
    cheque_fee_amount = request.form.get("cheque_fee_amount", type=float) or 0.0
    due_date_str = (request.form.get("due_date") or "").strip()
    due_date = None
    if due_date_str:
        try:
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        except Exception:
            pass

    db.session.add(Installment(
        plan_id=plan.id,
        seq=seq,
        amount_base=amount_base,
        cheque_fee_amount=cheque_fee_amount,
        amount_total=(amount_base + cheque_fee_amount),
        due_date=due_date,
        status="PENDING",
    ))
    plan.installments_count = plan.installments.count() + 1
    plan.total_amount = (plan.total_amount or 0) + amount_base  # جمع اصل
    plan.cheque_fee_total = (plan.cheque_fee_total or 0) + cheque_fee_amount
    db.session.commit()
    return redirect(url_for("courses.edit", course_id=plan.course_id))


# تسویه یک قسط → ساخت Payment(kind='tuition', status='paid') و لینک به installment
@bp.post("/installment/<int:inst_id>/settle")
@login_required
def settle_installment(inst_id: int):
    inst = Installment.query.get_or_404(inst_id)
    plan = inst.plan
    if inst.status == "PAID":
        return redirect(url_for("courses.edit", course_id=plan.course_id))

    p = Payment(
        kind="tuition",
        status="paid",
        amount=float(inst.amount_total or 0.0),
        title=f"قسط #{inst.seq} برنامه #{plan.id}",
        course_id=plan.course_id,
        student_id=plan.student_id,
        paid_at=datetime.utcnow(),
    )
    db.session.add(p); db.session.flush()
    inst.payment_id = p.id
    inst.status = "PAID"
    db.session.commit()
    return redirect(url_for("courses.edit", course_id=plan.course_id))


# حذف یک قسط از الگو (فقط وقتی پرداخت نشده)
@bp.post("/installment/<int:inst_id>/delete")
@login_required
def delete_installment(inst_id: int):
    inst = Installment.query.get_or_404(inst_id)
    plan = inst.plan
    if inst.status == "PAID":
        flash("قسط پرداخت‌شده قابل حذف نیست.", "warning")
        return redirect(url_for("courses.edit", course_id=plan.course_id))
    plan.total_amount = max((plan.total_amount or 0) - (inst.amount_base or 0), 0)
    plan.cheque_fee_total = max((plan.cheque_fee_total or 0) - (inst.cheque_fee_amount or 0), 0)
    db.session.delete(inst)
    db.session.commit()
    return redirect(url_for("courses.edit", course_id=plan.course_id))
