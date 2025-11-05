# app/blueprints/installments/routes.py
from __future__ import annotations
from datetime import date, timedelta, datetime
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import func
from app.extensions import db
from app.blueprints.installments import bp
from app.models.installment_plan import InstallmentPlan
from app.models.installment import Installment
from app.models.course import Course
from app.models.core import Student
from app.models.enrollment import Enrollment
from app.models.installment_cheque import InstallmentCheque
from app.utils.decorators import role_required

def _safe_float(x, default=0.0):
    try:
        if x is None: 
            return default
        return float(x)
    except Exception:
        return default
def _to_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _to_money(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None
# ---------------------------
# لیست برنامه‌های اقساط
# ---------------------------
@bp.get("/")
@role_required(["ADMIN","STUDENT"])
def index():
    plans = (InstallmentPlan.query
             .order_by(InstallmentPlan.id.desc())
             .all())
    rows = []
    for p in plans:
        insts = p.installments or []
        n = len(insts)
        total = sum((i.amount_total or 0) for i in insts)
        paid = sum((i.amount_total or 0) for i in insts if (i.status or "").upper() == "PAID")
        rows.append(dict(
            plan=p,
            count=n,
            total=int(total),
            paid=int(paid),
            remain=int(max(total - paid, 0))
        ))
    return render_template("installments/index.html", rows=rows)

# ---------------------------
# فرم ایجاد برنامه اقساط
# ---------------------------
@bp.get("/new")
@role_required(["ADMIN","STUDENT"])
def create_form():
    courses = Course.query.order_by(Course.title.asc()).all()
    students = Student.query.order_by(Student.id.desc()).all()
    enrollments = Enrollment.query.order_by(Enrollment.id.desc()).all()
    installments = (
        Installment.query
        .order_by(Installment.due_date.asc().nullslast(), Installment.id.desc())
        .all()
    )

    cheques = []
    if InstallmentCheque:
            cheques = (
            InstallmentCheque.query
            .order_by(
                getattr(InstallmentCheque, "created_at", None).desc().nullslast()
                if hasattr(InstallmentCheque, "created_at") else
                getattr(InstallmentCheque, "id").desc()
            )
            .limit(100)
            .all()
        )
    return render_template("installments/create.html",
                           courses=courses, students=students, enrollments=enrollments,installments=installments,
        cheques=cheques,)

# ---------------------------
# ثبت برنامه اقساط
# ---------------------------
@bp.post("/new")
@role_required(["ADMIN"])
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
    base_share = total_amount / count if count else 0
    fee_share = cheque_fee_total / count if cheque_fee_total>0 else 0.0

    # تولید اقساط با فاصله ماهانه (اولین سررسید = first_due_date)
    due = first_due_date
    for i in range(1, count+1):
        if not due:
            # اگر تاریخ شروع تعیین نشده بود، با فاصله‌ی 7*i روز پیش‌فرض می‌دهیم
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
        # ماه بعد – روش ساده (به اول ماه بعد می‌رود)
        due = (due.replace(day=28) + timedelta(days=4)).replace(day=1)

    db.session.commit()
    flash("برنامه اقساط با موفقیت ایجاد شد.", "success")
    return redirect(url_for("installments.index"))

# ---------------------------
# جزئیات یک برنامه اقساط
# ---------------------------
@bp.get("/<int:plan_id>")
@role_required(["ADMIN"])
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

# ---------------------------
# پرداخت/لغو پرداخت یک قسط
# ---------------------------
@bp.post("/<int:plan_id>/pay/<int:inst_id>")
@role_required(["ADMIN"])
def pay_installment(plan_id: int, inst_id: int):
    plan = InstallmentPlan.query.get_or_404(plan_id)
    inst = Installment.query.filter_by(id=inst_id, plan_id=plan.id).first_or_404()
    inst.status = "PAID"
    db.session.commit()
    flash("قسط پرداخت شد.", "success")
    return redirect(url_for("installments.details", plan_id=plan.id))

@bp.post("/<int:plan_id>/unpay/<int:inst_id>")
@role_required(["ADMIN"])
def unpay_installment(plan_id: int, inst_id: int):
    plan = InstallmentPlan.query.get_or_404(plan_id)
    inst = Installment.query.filter_by(id=inst_id, plan_id=plan.id).first_or_404()
    inst.status = "PENDING"
    db.session.commit()
    flash("پرداخت قسط لغو شد.", "info")
    return redirect(url_for("installments.details", plan_id=plan.id))

# -----------------------------------------------------------
# API سبک برای تب مالی پروفایل دانشجو: لیست اقساط دانشجو
# -----------------------------------------------------------
@bp.get("/student/<int:student_id>.json")
@role_required(["ADMIN"])
def api_student_installments(student_id: int):
    """
    خروجی扭:
    {
      "items": [
        {
          "plan_id": 1,
          "plan_title": "...",
          "course_id": 3,
          "course_title": "...",
          "installment_id": 10,
          "seq": 1,
          "due_date": "1403-07-15" (یا YYYY-MM-DD),
          "amount_base": 1000000,
          "cheque_fee_amount": 20000,
          "amount_total": 1020000,
          "status": "PENDING"/"PAID",
          "details_url": "/installments/1"
        },
        ...
      ]
    }
    """
    # برنامه‌هایی که مستقیماً به student_id وصل شده‌اند:
    direct_plans = InstallmentPlan.query.filter(
        InstallmentPlan.student_id == student_id
    ).all()

    # برنامه‌هایی که از مسیر Enrollment به دانشجو می‌رسند:
    en_plans = (InstallmentPlan.query
                .join(Enrollment, Enrollment.id == InstallmentPlan.enrollment_id)
                .filter(Enrollment.student_id == student_id)
                .all())

    plans = {p.id: p for p in (direct_plans + en_plans)}.values()

    items = []
    for p in plans:
        course_title = None
        if p.enrollment and p.enrollment.course:
            course_title = p.enrollment.course.title
        elif p.course:
            course_title = p.course.title

        for i in (p.installments or []):
            items.append({
                "plan_id": p.id,
                "plan_title": p.title or f"Plan #{p.id}",
                "course_id": p.course_id or (p.enrollment.course_id if p.enrollment else None),
                "course_title": course_title or "—",
                "installment_id": i.id,
                "seq": i.seq,
                "due_date": (i.due_date.isoformat() if getattr(i, "due_date", None) else None),
                "amount_base": int(i.amount_base or 0),
                "cheque_fee_amount": int(i.cheque_fee_amount or 0),
                "amount_total": int(i.amount_total or 0),
                "status": (i.status or "PENDING"),
                "details_url": url_for("installments.details", plan_id=p.id)
            })

    # مرتب‌سازی: نزدیک‌ترین سررسید اول
    items.sort(key=lambda r: (r.get("due_date") or "9999-12-31", r.get("seq") or 0))
    return jsonify({"items": items})
# ========= CRUD چکِ قسط =========
@bp.post("/cheques/new")
@role_required(["ADMIN"])
def cheque_new():
    if not InstallmentCheque:
        flash("مدل چک در سیستم فعال نیست.", "danger")
        return redirect(url_for("installments.create"))

    inst_id = request.form.get("installment_id", type=int)
    if not inst_id:
        flash("انتخاب قسط الزامی است.", "danger")
        return redirect(url_for("installments.create"))

    chq = InstallmentCheque()
    chq.installment_id = inst_id
    chq.cheque_number = (request.form.get("cheque_number") or "").strip()
    chq.bank_name = (request.form.get("bank_name") or "").strip() or None
    chq.amount = _to_money(request.form.get("amount"))
    chq.issue_date = _to_date(request.form.get("issue_date"))
    chq.due_date = _to_date(request.form.get("due_date"))
    chq.status = (request.form.get("status") or "").strip() or None
    chq.note = (request.form.get("note") or "").strip() or None

    try:
        db.session.add(chq)
        db.session.commit()
        flash("چک با موفقیت ثبت شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"خطا در ثبت چک: {e}", "danger")

    return redirect(url_for("installments.create"))


@bp.post("/cheques/<int:cheque_id>/edit")
@role_required(["ADMIN"])
def cheque_edit(cheque_id):
    if not InstallmentCheque:
        flash("مدل چک در سیستم فعال نیست.", "danger")
        return redirect(url_for("installments.create"))

    ch = InstallmentCheque.query.get_or_404(cheque_id)

    # امکان تغییر قسط مقصد (اختیاری)
    inst_id = request.form.get("installment_id", type=int)
    if inst_id:
        ch.installment_id = inst_id

    ch.cheque_number = (request.form.get("cheque_number") or ch.cheque_number or "").strip()
    ch.bank_name = (request.form.get("bank_name") or "").strip() or None
    amt = _to_money(request.form.get("amount"))
    if amt is not None:
        ch.amount = amt
    idt = _to_date(request.form.get("issue_date"))
    if idt:
        ch.issue_date = idt
    ddt = _to_date(request.form.get("due_date"))
    if ddt:
        ch.due_date = ddt
    ch.status = (request.form.get("status") or "").strip() or ch.status
    ch.note = (request.form.get("note") or "").strip() or ch.note

    try:
        db.session.commit()
        flash("چک ویرایش شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"خطا در ویرایش: {e}", "danger")

    return redirect(url_for("installments.create"))


@bp.post("/cheques/<int:cheque_id>/delete")
@role_required(["ADMIN"])
def cheque_delete(cheque_id):
    if not InstallmentCheque:
        flash("مدل چک در سیستم فعال نیست.", "danger")
        return redirect(url_for("installments.create"))

    ch = InstallmentCheque.query.get_or_404(cheque_id)
    try:
        db.session.delete(ch)
        db.session.commit()
        flash("چک حذف شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"حذف چک با خطا مواجه شد: {e}", "danger")

    return redirect(url_for("installments.create"))
@bp.post("/<int:inst_id>/edit")
@role_required(["ADMIN"])
def installment_edit(inst_id):
    inst = Installment.query.get_or_404(inst_id)

    # تغییر فیلدها فقط اگر در مدل موجود باشند
    title = (request.form.get("title") or "").strip()
    if title and hasattr(inst, "title"):
        inst.title = title

    if hasattr(inst, "seq"):
        seq = request.form.get("seq", type=int)
        if seq is not None:
            inst.seq = seq

    # مبالغ
    ab = _to_money(request.form.get("amount_base"))
    if (ab is not None) and hasattr(inst, "amount_base"):
        inst.amount_base = ab

    cf = _to_money(request.form.get("cheque_fee_amount"))
    if (cf is not None) and hasattr(inst, "cheque_fee_amount"):
        inst.cheque_fee_amount = cf

    at = _to_money(request.form.get("amount_total"))
    if (at is not None) and hasattr(inst, "amount_total"):
        inst.amount_total = at
    else:
        # اگر amount_total داده نشد و فیلدها بودند، جمع بزن
        if hasattr(inst, "amount_total") and hasattr(inst, "amount_base") and hasattr(inst, "cheque_fee_amount"):
            try:
                inst.amount_total = (inst.amount_base or 0) + (inst.cheque_fee_amount or 0)
            except Exception:
                pass

    # تاریخ سررسید
    dd = _to_date(request.form.get("due_date"))
    if dd and hasattr(inst, "due_date"):
        inst.due_date = dd

    # وضعیت و توضیح
    status = (request.form.get("status") or "").strip()
    if status and hasattr(inst, "status"):
        inst.status = status.upper()

    note = (request.form.get("note") or "").strip()
    if hasattr(inst, "note"):
        inst.note = note or None

    # امکان تغییر لینک به پلن (اختیاری)
    plan_id = request.form.get("plan_id", type=int)
    if plan_id and hasattr(inst, "plan_id"):
        inst.plan_id = plan_id
    if plan_id and hasattr(inst, "installment_plan_id"):
        inst.installment_plan_id = plan_id

    try:
        db.session.commit()
        flash("قسط ویرایش شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"خطا در ویرایش قسط: {e}", "danger")
    return redirect(url_for("installments.create"))


@bp.post("/<int:inst_id>/delete")
@role_required(["ADMIN"])
def installment_delete(inst_id):
    inst = Installment.query.get_or_404(inst_id)

    # 🚫 اگر پرداخت شده، اجازه حذف نده
    status = (getattr(inst, "status", "") or "").upper()
    if status in {"PAID", "SETTLED"}:
        flash("قسط پرداخت‌شده قابل حذف نیست.", "warning")
        return redirect(url_for("installments.details", inst_id=inst.id))

    try:
        db.session.delete(inst)
        db.session.commit()
        flash("قسط با موفقیت حذف شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"خطا در حذف قسط: {e}", "danger")

    # برگشت به لیست
    return redirect(url_for("installments.create"))