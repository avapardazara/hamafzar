# app/blueprints/installments/routes.py
from __future__ import annotations
from datetime import date, timedelta, datetime
from typing import Optional
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

# ---------------------------------------
# Helpers
# ---------------------------------------
def _safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _safe_int(x, default=0):
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default

def _parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def _add_months(d: date, months: int) -> date:
    """افزایش ماهانه تقویمی بدون وابستگی خارجی."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # روز را به آخرین روز ماه جدید فیت کنیم
    # روز هدف = حداقلِ روز فعلی و آخرین روز ماه مقصد
    # محاسبه آخرین روز ماه مقصد:
    if m == 12:
        next_month_first = date(y + 1, 1, 1)
    else:
        next_month_first = date(y, m + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).day
    day = min(d.day, last_day)
    return date(y, m, day)

def _enrollment_fee(en: Enrollment, course: Course) -> float:
    """
    مبلغ پایه شهریه برای این ثبت‌نام.
    اگر روی Enrollment فیلد override شهریه دارید، در اولویت بخوانید.
    در غیر این صورت از Course.fee_per_student استفاده می‌کنیم.
    """
    # اگر مدل Enrollment شما فیلدی مثل fee_per_student دارد، اینجا بخوانید:
    if hasattr(en, "fee_per_student") and (getattr(en, "fee_per_student") is not None):
        try:
            return float(getattr(en, "fee_per_student") or 0)  # type: ignore
        except Exception:
            pass
    # پیش‌فرض: از Course
    try:
        return float(course.fee_per_student or 0)
    except Exception:
        return 0.0

# ---------------------------------------
# لیست برنامه‌های اقساط
# ---------------------------------------
@bp.get("/")
@login_required
def index():
    plans = (
        InstallmentPlan.query
        .order_by(InstallmentPlan.id.desc())
        .all()
    )
    # مجموع‌ها برای نمایش سریع
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

# ---------------------------------------
# ایجاد برنامه اقساط (فرم)
# ورودی اختیاری: ?course_id=...
# ---------------------------------------
@bp.get("/new")
@login_required
def create_form():
    course_id = request.args.get("course_id", type=int)
    course = None
    courses = []
    enrollments = []
    students = []

    if course_id:
        course = Course.query.get_or_404(course_id)
        # فقط ثبت‌نام‌های همین دوره
        enrollments = (
            Enrollment.query
            .filter(Enrollment.course_id == course.id)
            .order_by(Enrollment.id.desc())
            .all()
        )
        # دانشجوها برای نمایش لیبل بهتر (اختیاری)
        student_ids = [e.student_id for e in enrollments]
        if student_ids:
            students = (
                Student.query
                .filter(Student.id.in_(student_ids))
                .order_by(Student.id.desc())
                .all()
            )
    else:
        # مسیر عمومی: همه چیز آزاد است
        courses = Course.query.order_by(Course.title.asc()).all()
        students = Student.query.order_by(Student.id.desc()).all()
        enrollments = Enrollment.query.order_by(Enrollment.id.desc()).all()

    return render_template(
        "installments/create.html",
        course=course,
        courses=courses,
        students=students,
        enrollments=enrollments
    )

# ---------------------------------------
# ایجاد برنامه اقساط (ارسال)
# فرم باید یکی از این‌ها را بدهد:
#  - enrollment_id (ترجیحی)
#  - یا (course_id و student_id) که تبدیل به enrollment می‌شود
# سایر فیلدها:
#  - down_payment (پیش‌پرداخت)
#  - installments_count
#  - first_due_date
#  - month_interval (1..6)
#  - use_cheques, cheque_fee_percent
# ---------------------------------------
@bp.post("/new")
@login_required
def create_submit():
    title = (request.form.get("title") or "").strip()

    # 1) تشخیص ثبت‌نام
    enrollment_id = request.form.get("enrollment_id", type=int)
    course_id = request.form.get("course_id", type=int)
    student_id = request.form.get("student_id", type=int)

    enrollment: Optional[Enrollment] = None
    course: Optional[Course] = None

    if enrollment_id:
        enrollment = Enrollment.query.get(enrollment_id)
        if not enrollment:
            flash("ثبت‌نام انتخاب‌شده یافت نشد.", "error")
            return redirect(url_for("installments.create_form"))
        course = Course.query.get(enrollment.course_id)
        if not course:
            flash("دورهٔ مرتبط با ثبت‌نام یافت نشد.", "error")
            return redirect(url_for("installments.create_form"))
    else:
        if not (course_id and student_id):
            flash("برای ایجاد اقساط، ثبت‌نام یا (دوره و دانشجو) لازم است.", "error")
            return redirect(url_for("installments.create_form"))
        course = Course.query.get_or_404(course_id)
        enrollment = (
            Enrollment.query
            .filter(Enrollment.course_id == course.id, Enrollment.student_id == student_id)
            .first()
        )
        if not enrollment:
            flash("برای این دانشجو در این دوره ثبت‌نامی وجود ندارد.", "error")
            return redirect(url_for("installments.create_form", course_id=course.id))

    # 2) مبلغ پایه از ثبت‌نام/دوره (سمت سرور)
    base_amount = _enrollment_fee(enrollment, course)

    # 3) پارامترهای اقساط
    down_payment = _safe_float(request.form.get("down_payment"), 0.0)
    count = max(_safe_int(request.form.get("installments_count"), 1), 1)

    # تاریخ اولین قسط + فاصله ماهانه
    first_due_date = _parse_date((request.form.get("first_due_date") or "").strip())
    month_interval = request.form.get("month_interval", type=int) or 1
    month_interval = max(1, min(month_interval, 6))

    # چک/کارمزد
    use_cheques = True if request.form.get("use_cheques") == "1" else False
    cheque_fee_percent = _safe_float(request.form.get("cheque_fee_percent"), 0.0)

    # 4) محاسبات
    principal_total = max(base_amount - max(down_payment, 0.0), 0.0)
    cheque_fee_total = (principal_total * (cheque_fee_percent / 100.0)) if (use_cheques and cheque_fee_percent > 0) else 0.0
    total_amount = principal_total + cheque_fee_total

    # سهم هر قسط
    base_share = principal_total / count if count else 0.0
    fee_share = cheque_fee_total / count if (count and cheque_fee_total > 0) else 0.0

    # 5) ایجاد Plan
    plan = InstallmentPlan(
        title=title or None,
        course_id=course.id,
        student_id=enrollment.student_id,
        enrollment_id=enrollment.id,
        total_amount=total_amount,
        installments_count=count,
        use_cheques=use_cheques,
        cheque_fee_percent=cheque_fee_percent,
        cheque_fee_total=cheque_fee_total,
        first_due_date=first_due_date,
        status="OPEN",
    )
    db.session.add(plan)
    db.session.flush()  # برای داشتن plan.id

    # 6) تولید اقساط با فاصله ماهانه
    due = first_due_date or (date.today() + timedelta(days=7))  # اگر تاریخ شروع نداد، یک هفته بعد
    for i in range(1, count + 1):
        inst = Installment(
            plan_id=plan.id,
            seq=i,
            amount_base=base_share,
            cheque_fee_amount=fee_share,
            amount_total=(base_share + fee_share),
            due_date=due,
            status="PENDING",
        )
        db.session.add(inst)
        # تاریخ بعدی
        due = _add_months(due, month_interval)

    db.session.commit()
    flash("برنامه اقساط با موفقیت ایجاد شد.", "success")
    return redirect(url_for("installments.index"))

# ---------------------------------------
# جزئیات برنامه اقساط
# ---------------------------------------
@bp.get("/<int:plan_id>")
@login_required
def details(plan_id: int):
    from app.models.installment_plan import InstallmentPlan
    from app.models.installment import Installment
    from app.models.enrollment import Enrollment
    from app.models.core import Student
    from app.models.course import Course

    plan = InstallmentPlan.query.get_or_404(plan_id)

    # --- resolve course & student names safely (بدون نیاز به رابطه‌ی تعریف‌شده)
    course_title = "—"
    student_name = "—"

    # اولویت با enrollment اگر ست شده
    en = None
    if getattr(plan, "enrollment_id", None):
        en = Enrollment.query.get(plan.enrollment_id)

    # course_id از plan یا از enrollment
    cid = getattr(plan, "course_id", None)
    if not cid and en:
        cid = en.course_id
    if cid:
        c = Course.query.get(cid)
        if c:
            course_title = c.title

    # student از plan یا از enrollment
    sid = getattr(plan, "student_id", None)
    if not sid and en:
        sid = en.student_id
    if sid:
        st = Student.query.get(sid)
        if st:
            # اگر full_name داری از همون استفاده می‌کنیم؛ وگرنه first/last
            if hasattr(st, "full_name") and st.full_name:
                student_name = st.full_name
            else:
                fn = (st.first_name or "").strip()
                ln = (st.last_name or "").strip()
                student_name = (fn + " " + ln).strip() or f"دانشجو #{st.id}"

    # --- اقساط
    insts = (
        Installment.query
        .filter(Installment.plan_id == plan.id)
        .order_by(Installment.seq.asc())
        .all()
    )

    # --- محاسبه جمع‌ها «فقط از روی amount_total» تا با تب مالی یکی شود
    total = sum((i.amount_total or 0) for i in insts)
    paid  = sum((i.amount_total or 0) for i in insts if ((i.status or "").upper() == "PAID"))
    remain = max(total - paid, 0)

    return render_template(
        "installments/details.html",
        plan=plan,
        installments=insts,
        # مقادیر موردنیاز همان‌هایی که در قالب استفاده می‌کنی:
        total=int(total),
        paid=int(paid),
        remain=int(remain),
        # نام‌های آماده برای نمایش (تا دیگه به plan.enrollment دست نزنی)
        course_title=course_title,
        student_name=student_name,
    )
# ---------------------------------------
# عملیات پرداخت/لغو پرداخت یک قسط
# (حداقل تغییر: فقط وضعیت را جابه‌جا می‌کنیم.
#  اگر مدل مالی دارید، اینجا می‌توانید رکورد پرداخت هم درج کنید.)
# ---------------------------------------
@bp.post("/installments/<int:inst_id>/pay")
@login_required
def pay_installment(inst_id: int):
    inst = Installment.query.get_or_404(inst_id)
    if (inst.status or "").upper() == "PAID":
        flash("این قسط قبلاً پرداخت شده است.", "info")
        return redirect(url_for("installments.details", plan_id=inst.plan_id))

    inst.status = "PAID"
    # اگر فیلد paid_at دارید:
    if hasattr(inst, "paid_at"):
        setattr(inst, "paid_at", datetime.utcnow())

    db.session.commit()
    flash("پرداخت قسط ثبت شد.", "success")
    return redirect(url_for("installments.details", plan_id=inst.plan_id))

@bp.post("/installments/<int:inst_id>/unpay")
@login_required
def unpay_installment(inst_id: int):
    inst = Installment.query.get_or_404(inst_id)
    if (inst.status or "").upper() != "PAID":
        flash("این قسط در وضعیت پرداخت‌شده نیست.", "info")
        return redirect(url_for("installments.details", plan_id=inst.plan_id))

    inst.status = "PENDING"
    if hasattr(inst, "paid_at"):
        setattr(inst, "paid_at", None)

    db.session.commit()
    flash("وضعیت پرداخت قسط لغو شد.", "success")
    return redirect(url_for("installments.details", plan_id=inst.plan_id))
# ============================
# Helper: دریافت اقساط دانشجو برای استفاده در قالب‌ها
# ============================

@bp.app_template_global("get_student_installments")
def get_student_installments(student_id: int):
    """
    خروجی: لیستی از دیکشنری‌ها. هر مورد = یک پلان + اقساطش
    شامل پلان‌های متصل مستقیم به student_id و نیز پلان‌هایی که از طریق Enrollment به همان دانشجو می‌رسند.
    """
    from sqlalchemy import or_
    from app.models.installment_plan import InstallmentPlan
    from app.models.installment import Installment
    from app.models.enrollment import Enrollment
    from app.models.course import Course
    from app.models.core import Student

    # همه‌ی پلان‌هایی که:
    # 1) مستقیماً student_id دارند
    # 2) یا enrollment_id دارند که متعلق به همین student است
    plans_q = (
        db.session.query(InstallmentPlan)
        .outerjoin(Enrollment, Enrollment.id == InstallmentPlan.enrollment_id)
        .filter(
            or_(
                InstallmentPlan.student_id == student_id,
                Enrollment.student_id == student_id
            )
        )
        .order_by(InstallmentPlan.id.desc())
    )
    plans = plans_q.all()

    out = []
    for p in plans:
        insts = (
            db.session.query(Installment)
            .filter(Installment.plan_id == p.id)
            .order_by(Installment.seq.asc())
            .all()
        )
        total = sum((i.amount_total or 0) for i in insts)
        paid  = sum((i.amount_total or 0) for i in insts if (i.status or "").upper() == "PAID")
        remain = max(total - paid, 0)

        # تشخیص دوره و دانشجو برای نمایش
        course_obj = None
        student_obj = None
        if p.enrollment:
            course_obj = p.enrollment.course
            student_obj = p.enrollment.student
        if not course_obj:
            course_obj = p.course
        if not student_obj:
            student_obj = p.student

        out.append({
            "plan": p,
            "installments": insts,
            "total": int(total),
            "paid": int(paid),
            "remain": int(remain),
            "course": course_obj,
            "student": student_obj,
        })
    return out
