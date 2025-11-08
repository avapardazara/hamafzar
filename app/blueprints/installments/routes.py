# app/blueprints/installments/routes.py
from __future__ import annotations
from datetime import date, timedelta, datetime
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
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
from app.models.mentor import Mentor
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
  
def _inst_to_dict(inst: Installment) -> dict:
    return {
        "id": inst.id,
        "plan_id": getattr(inst, "plan_id", None) or getattr(inst, "installment_plan_id", None),
        "seq": getattr(inst, "seq", None),
        "title": getattr(inst, "title", None),
        "amount_base": int((getattr(inst, "amount_base", 0) or 0)),
        "cheque_fee_amount": int((getattr(inst, "cheque_fee_amount", 0) or 0)),
        "amount_total": int((getattr(inst, "amount_total", 0) or 0)),
        "due_date": (inst.due_date.isoformat() if getattr(inst, "due_date", None) else None),
        "status": (getattr(inst, "status", None) or "PENDING"),
        "note": getattr(inst, "note", None),
    }

def _plan_totals(plan_id: int) -> dict:
    insts = Installment.query.filter(
        (Installment.plan_id == plan_id) | (getattr(Installment, "installment_plan_id", None) == plan_id)
    ).all()
    total = sum((i.amount_total or 0) for i in insts)
    paid = sum((i.amount_total or 0) for i in insts if (i.status or "").upper() == "PAID")
    return {
        "count": len(insts),
        "total": int(total),
        "paid": int(paid),
        "remain": int(max(total - paid, 0)),
    }

def _get_data():
    """Accept both JSON and form-encoded payloads."""
    return request.get_json(silent=True) or request.form  
# ---------------------------
# لیست برنامه‌های اقساط
# ---------------------------
@bp.get("/")
@login_required
@role_required(["admin","STUDENT"])
def index():
    # لیست پلن‌ها + پرلود قسط‌ها برای محاسبات (جلوگیری از N+1)
    plans = (
        InstallmentPlan.query
        .options(db.joinedload(InstallmentPlan.installments))
        .order_by(InstallmentPlan.id.desc())
        .all()
    )

    # آمار هر پلن (اختیاری؛ اگر تمپلیت لازم داشت می‌توانید استفاده کنید)
    stats = {}
    for p in plans:
        insts = p.installments or []
        n = len(insts)
        total = sum((i.amount_total or 0) for i in insts)
        paid = sum((i.amount_total or 0) for i in insts if (i.status or "").upper() == "PAID")
        stats[p.id] = dict(
            count=n,
            total=int(total),
            paid=int(paid),
            remain=int(max(total - paid, 0)),
        )

    # این دو در index.html برای مدال/فیلترها استفاده می‌شوند
    students = Student.query.order_by(Student.id.desc()).all()
    courses = Course.query.order_by(Course.title.asc()).all()

    # نکته مهم: اینجا plans پاس می‌دهیم نه rows
    return render_template(
        "installments/index.html",
        plans=plans,
        students=students,
        courses=courses,
        stats=stats,   # اگر در تمپلیت مصرف شد؛ بودنش ضرر ندارد
    )
# ---------------------------
# فرم ایجاد برنامه اقساط
# ---------------------------
@bp.get("/new")
@login_required
@role_required(["admin","STUDENT"])
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
@login_required
@role_required(["admin"])
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
@login_required
@role_required(["admin"])
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
@login_required
@role_required(["admin"])
def pay_installment(plan_id: int, inst_id: int):
    plan = InstallmentPlan.query.get_or_404(plan_id)
    inst = Installment.query.filter_by(id=inst_id, plan_id=plan.id).first_or_404()
    inst.status = "PAID"
    db.session.commit()
    flash("قسط پرداخت شد.", "success")
    return redirect(url_for("installments.details", plan_id=plan.id))

@bp.post("/<int:plan_id>/unpay/<int:inst_id>")
@login_required
@role_required(["admin"])
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
@login_required
@role_required(["admin"])
def api_student_installments(student_id: int):
    role = (current_user.role or "").upper()

    # محدودیت نقش دانشجو: فقط به داده‌های خودش دسترسی داشته باشد
    if role == "STUDENT":
        me = Student.query.filter_by(user_id=current_user.id).first()
        if not me or me.id != student_id:
            return jsonify({"error": "FORBIDDEN"}), 403

    # (اختیاری) محدودیت منتور: فقط اگر دانشجو در یکی از دوره‌های منتور است
    if role == "MENTOR":
        m = Mentor.query.filter_by(user_id=current_user.id).first()
        if not m:
            return jsonify({"items": [], "plans": [], "summary": {"sum_total": 0, "sum_paid": 0, "sum_remain": 0}})
        # تأیید اینکه دانشجو حداقل یک ثبت‌نام در دوره‌های همین منتور دارد؛
        # اگر سخت‌گیرانه می‌خواهی enforce کنی، می‌شود اینجا چک اضافه نوشت.
        # برای سادگی فعلاً از همان فیلترهای پایین استفاده می‌کنیم.

    # برنامه‌هایی که مستقیماً به student_id وصل شده‌اند:
    direct_plans = InstallmentPlan.query.filter(InstallmentPlan.student_id == student_id)

    # برنامه‌هایی که از مسیر Enrollment به دانشجو می‌رسند:
    via_enrollment = (InstallmentPlan.query
                      .join(Enrollment, Enrollment.id == InstallmentPlan.enrollment_id)
                      .filter(Enrollment.student_id == student_id))

    # اگر منتور است، دایره‌ی دید را به دوره‌های خودش محدود کن
    if role == "MENTOR":
        m = Mentor.query.filter_by(user_id=current_user.id).first()
        if m:
            direct_plans = (direct_plans.join(Course, Course.id == InstallmentPlan.course_id)
                                         .filter(Course.mentor_id == m.id))
            via_enrollment = (via_enrollment.join(Course, Course.id == InstallmentPlan.course_id)
                                             .filter(Course.mentor_id == m.id))

    # ادغام یکتا
    plans = {p.id: p for p in direct_plans.all() + via_enrollment.all()}.values()

    items = []
    plans_payload = []

    sum_total = 0
    sum_paid = 0

    for p in plans:
        # عنوان و دوره
        course_title = None
        course_price = None
        if p.enrollment and p.enrollment.course:
            course_title = p.enrollment.course.title
            course_price = getattr(p.enrollment.course, "price", None)
        elif p.course:
            course_title = p.course.title
            course_price = getattr(p.course, "price", None)

        insts = p.installments or []
        plan_total_calc = sum((i.amount_total or 0) for i in insts)
        plan_total_amount = int((p.total_amount or 0) or plan_total_calc)
        plan_paid = int(sum((i.amount_total or 0) for i in insts if (i.status or "").upper() == "PAID"))
        plan_remain = int(max(plan_total_amount - plan_paid, 0))

        sum_total += plan_total_amount
        sum_paid += plan_paid

        # خلاصه هر پلن (برای نمایش «هزینه دوره/پلن» در تب مالی)
        plans_payload.append({
            "plan_id": p.id,
            "plan_title": p.title or f"Plan #{p.id}",
            "course_id": p.course_id or (p.enrollment.course_id if p.enrollment else None),
            "course_title": course_title or "—",
            "course_price": int(course_price) if course_price is not None else None,
            "plan_total_amount": plan_total_amount,
            "plan_paid": plan_paid,
            "plan_remain": plan_remain,
            "details_url": url_for("installments.details", plan_id=p.id)
        })

        # آیتم‌های قسط
        for i in insts:
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

    summary = {
        "sum_total": int(sum_total),
        "sum_paid": int(sum_paid),
        "sum_remain": int(max(sum_total - sum_paid, 0))
    }

    return jsonify({"items": items, "plans": plans_payload, "summary": summary})

# ========= CRUD چکِ قسط =========
@bp.post("/cheques/new")
@login_required
@role_required(["admin"])
def cheque_new():
    if not InstallmentCheque:
        flash("مدل چک در سیستم فعال نیست.", "danger")
        return redirect(url_for("installments.create_form"))

    inst_id = request.form.get("installment_id", type=int)
    if not inst_id:
        flash("انتخاب قسط الزامی است.", "danger")
        return redirect(url_for("installments.create_form"))

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

    return redirect(url_for("installments.create_form"))




@bp.post("/cheques/<int:cheque_id>/edit")
@login_required
@role_required(["admin"])
def cheque_edit(cheque_id):
    if not InstallmentCheque:
        flash("مدل چک در سیستم فعال نیست.", "danger")
        return redirect(url_for("installments.create_form"))

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

    return redirect(url_for("installments.create_form"))


@bp.post("/cheques/<int:cheque_id>/delete")
@login_required
@role_required(["admin"])
def cheque_delete(cheque_id):
    if not InstallmentCheque:
        flash("مدل چک در سیستم فعال نیست.", "danger")
        return redirect(url_for("installments.create_form"))

    ch = InstallmentCheque.query.get_or_404(cheque_id)
    try:
        db.session.delete(ch)
        db.session.commit()
        flash("چک حذف شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"حذف چک با خطا مواجه شد: {e}", "danger")

    return redirect(url_for("installments.create_form"))
@bp.post("/<int:inst_id>/edit")
@login_required
@role_required(["admin"])
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
    return redirect(url_for("installments.create_form"))


@bp.post("/<int:inst_id>/delete")
@login_required
@role_required(["admin"])
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
    return redirect(url_for("installments.create_form"))

@bp.post("/api/plans/<int:plan_id>/installments/add")
@role_required(["admin"])
def api_add_installment(plan_id):
    # فقط برای اطمینان: پلن باید وجود داشته باشد
    plan = InstallmentPlan.query.get_or_404(plan_id)

    data = _get_data()

    # seq: اگر نیامده بود، بعدی را حساب کن
    seq = None
    try:
        seq = int(data.get("seq")) if data.get("seq") not in (None, "",) else None
    except Exception:
        seq = None
    if not seq and hasattr(Installment, "seq"):
        max_seq = db.session.query(func.max(Installment.seq)).filter(Installment.plan_id == plan.id).scalar() or 0
        seq = max_seq + 1

    amount_base = _to_money(data.get("amount_base"))
    cheque_fee_amount = _to_money(data.get("cheque_fee_amount"))
    amount_total = _to_money(data.get("amount_total"))
    if amount_total is None:
        amount_total = (amount_base or 0) + (cheque_fee_amount or 0)

    inst = Installment(
        plan_id=plan.id if "plan_id" in Installment.__table__.c else None,
        **({"seq": seq} if hasattr(Installment, "seq") else {}),
        **({"title": (data.get("title") or None)} if hasattr(Installment, "title") else {}),
        **({"amount_base": amount_base} if hasattr(Installment, "amount_base") else {}),
        **({"cheque_fee_amount": cheque_fee_amount} if hasattr(Installment, "cheque_fee_amount") else {}),
        **({"amount_total": amount_total} if hasattr(Installment, "amount_total") else {}),
        **({"due_date": _to_date(data.get("due_date"))} if hasattr(Installment, "due_date") else {}),
        **({"status": (data.get("status") or "PENDING").upper()} if hasattr(Installment, "status") else {}),
        **({"note": (data.get("note") or None)} if hasattr(Installment, "note") else {}),
    )
    db.session.add(inst)
    db.session.commit()
    return jsonify({"ok": True, "item": _inst_to_dict(inst), "totals": _plan_totals(plan.id)})

# ---------- API: update installment ----------
@bp.post("/api/installments/<int:inst_id>/update")
@role_required(["admin"])
def api_update_installment(inst_id):
    inst = Installment.query.get_or_404(inst_id)
    data = _get_data()

    # فیلدها اگر در مدل وجود دارند
    if hasattr(inst, "title"):
        t = (data.get("title") or "").strip()
        if t != "": inst.title = t
    if hasattr(inst, "seq") and data.get("seq"):
        try: inst.seq = int(data.get("seq"))
        except Exception: pass
    if hasattr(inst, "amount_base"):
        v = _to_money(data.get("amount_base"))
        if v is not None: inst.amount_base = v
    if hasattr(inst, "cheque_fee_amount"):
        v = _to_money(data.get("cheque_fee_amount"))
        if v is not None: inst.cheque_fee_amount = v
    if hasattr(inst, "amount_total"):
        v = _to_money(data.get("amount_total"))
        if v is not None:
            inst.amount_total = v
        else:
            # اگر نیامد، از جمع اجزاء بساز
            try:
                inst.amount_total = (inst.amount_base or 0) + (inst.cheque_fee_amount or 0)
            except Exception:
                pass
    if hasattr(inst, "due_date"):
        d = _to_date(data.get("due_date"))
        if d: inst.due_date = d
    if hasattr(inst, "status") and data.get("status"):
        inst.status = str(data.get("status")).upper()
    if hasattr(inst, "note"):
        inst.note = (data.get("note") or None)

    db.session.commit()
    plan_id = getattr(inst, "plan_id", None) or getattr(inst, "installment_plan_id", None)
    return jsonify({"ok": True, "item": _inst_to_dict(inst), "totals": _plan_totals(plan_id)})

# ---------- API: mark paid ----------
@bp.post("/api/installments/<int:inst_id>/mark_paid")
@role_required(["admin"])
def api_mark_paid(inst_id):
    inst = Installment.query.get_or_404(inst_id)
    if hasattr(inst, "status"):
        inst.status = "PAID"
    db.session.commit()
    plan_id = getattr(inst, "plan_id", None) or getattr(inst, "installment_plan_id", None)
    return jsonify({"ok": True, "item": _inst_to_dict(inst), "totals": _plan_totals(plan_id)})

# ---------- API: mark unpaid ----------
@bp.post("/api/installments/<int:inst_id>/mark_unpaid")
@role_required(["admin"])
def api_mark_unpaid(inst_id):
    inst = Installment.query.get_or_404(inst_id)
    if hasattr(inst, "status"):
        inst.status = "PENDING"
    db.session.commit()
    plan_id = getattr(inst, "plan_id", None) or getattr(inst, "installment_plan_id", None)
    return jsonify({"ok": True, "item": _inst_to_dict(inst), "totals": _plan_totals(plan_id)})

# ---------- API: delete installment ----------
@bp.post("/api/installments/<int:inst_id>/delete")
@role_required(["admin"])
def api_delete_installment(inst_id):
    inst = Installment.query.get_or_404(inst_id)

    # هم‌راستا با محدودیت قبلی: پرداخت‌شده را حذف نکن
    status = (getattr(inst, "status", "") or "").upper()
    if status in {"PAID", "SETTLED"}:
        return jsonify({"ok": False, "error": "PAID_INSTALLMENT_CANNOT_BE_DELETED"}), 400

    plan_id = getattr(inst, "plan_id", None) or getattr(inst, "installment_plan_id", None)
    try:
        db.session.delete(inst)
        db.session.commit()
        return jsonify({"ok": True, "totals": _plan_totals(plan_id)})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
@bp.post("/<int:plan_id>/edit")
@role_required(["admin"])
def plan_edit(plan_id: int):
    plan = InstallmentPlan.query.get_or_404(plan_id)
    d = request.form

    # فیلدهای مجاز
    title = (d.get("title") or "").strip()
    if title:
        plan.title = title

    if d.get("status"):
        plan.status = str(d.get("status")).upper()

    # اعداد
    def _num(x):
        try:
            return float(str(x).replace(",", ""))
        except Exception:
            return None

    v = _num(d.get("total_amount"))
    if v is not None:
        plan.total_amount = v

    cnt = d.get("installments_count")
    if cnt and str(cnt).isdigit():
        plan.installments_count = int(cnt)

    # تاریخ
    fd = (d.get("first_due_date") or "").strip()
    if fd:
        try:
            plan.first_due_date = datetime.strptime(fd, "%Y-%m-%d").date()
        except Exception:
            pass

    # چک‌ها
    plan.use_cheques = True if str(d.get("use_cheques", "0")) == "1" else False
    fee = _num(d.get("cheque_fee_percent"))
    if fee is not None:
        plan.cheque_fee_percent = fee

    db.session.commit()
    flash("برنامه اقساط با موفقیت ویرایش شد.", "success")
    return redirect(url_for("installments.index"))