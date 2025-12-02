# app/blueprints/mentors/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import func, literal
from sqlalchemy.orm.attributes import InstrumentedAttribute
from ...extensions import db
from ...models.mentor import Mentor
from ...models.course import Course
from ...models.enrollment import Enrollment
from ...models.mentor_payment import MentorPayment
from ...utils.files import save_mentor_avatar  # همان util موجود
from ...models.payment import Payment
from ...models.installment_plan import InstallmentPlan
from ...models.installment import Installment
from sqlalchemy import or_
from flask_login import current_user
from app.models.user import User
from werkzeug.security import generate_password_hash
from ...models.core import Student
bp = Blueprint("mentors", __name__, url_prefix="/mentors")


# -------------------------------
# Helpers
# -------------------------------
def _attach_account_if_requested(form, person_obj, role_name="MENTOR"):
    create_flag = (form.get("acc_create") or "") == "1"
    if not create_flag:
        return True, None

    username = (form.get("acc_username") or "").strip()
    email    = (form.get("acc_email") or (getattr(person_obj, "email", "") or "")).strip()
    pw1      = form.get("acc_password") or ""
    pw2      = form.get("acc_password2") or ""

    if not username or not email:
        return False, "نام کاربری و ایمیل برای ساخت حساب الزامی است."
    if pw1 != pw2:
        return False, "رمزهای عبور یکسان نیستند."
    if len(pw1) < 6:
        return False, "طول رمز باید حداقل ۶ کاراکتر باشد."
    if User.query.filter_by(username=username).first():
        return False, "این نام کاربری قبلاً ثبت شده است."
    if User.query.filter_by(email=email).first():
        return False, "این ایمیل قبلاً ثبت شده است."

    u = User(username=username, email=email, role="MENTOR")
    u.password_hash = generate_password_hash(pw1)
    db.session.add(u)
    db.session.flush()
    if hasattr(person_obj, "user_id"):
        person_obj.user_id = u.id
    return True, None
def _safe_num(val, default=0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default

def _inst_total(i):
    return int(
        (getattr(i, "amount_total", None)
         or (getattr(i, "amount_base", 0) or 0) + (getattr(i, "cheque_fee_amount", 0) or 0)) or 0
    )

def _inst_paid_amount(i):
    total = _inst_total(i)
    for attr in ("amount_paid", "paid_amount", "amount_received"):
        val = getattr(i, attr, None)
        if val is not None:
            try:
                v = int(val)
                return min(max(v, 0), total)
            except Exception:
                pass
    if (getattr(i, "status", "") or "").upper() in {"PAID", "SETTLED"}:
        return total
    return 0

def _mentor_share_percent(course) -> float:
    raw = None
    for nm in ("mentor_share_percent", "mentor_percent", "mentor_share", "mentor_ratio"):
        if hasattr(course, nm):
            raw = getattr(course, nm)
            if raw is not None:
                break
    try:
        v = float(raw)
    except Exception:
        return 0.0
    if v < 0:
        return 0.0
    return v / 100.0 if v > 1.0 else v

def _has_installments_for_enrollment(enrollment_id: int) -> bool:
    if hasattr(InstallmentPlan, "enrollment_id"):
        return bool(
            db.session.query(InstallmentPlan.id)
            .filter(InstallmentPlan.enrollment_id == enrollment_id)
            .first()
        )
    # اگر ساختار متفاوت باشد، اینجا می‌توان لینک دیگری را بررسی کرد
    return False

def _sum_paid_tuition_for(enrollment_id: int | None, student_id: int | None, course_id: int | None) -> float:
    """جمع پرداخت‌های شهریه (inflow, paid/settled). تحمل ستون enrollment_id و فیلترهای جایگزین."""
    amount_col = getattr(Payment, "amount")
    status_ok = func.coalesce(func.lower(getattr(Payment, "status")), "pending").in_(("paid", "settled"))
    kind_col = func.lower(getattr(Payment, "kind"))
    inflow = or_(kind_col.is_(None), ~kind_col.in_(("mentor_share", "expense", "refund")))

    q = db.session.query(func.coalesce(func.sum(amount_col), 0.0)).filter(amount_col > 0, status_ok, inflow)

    if enrollment_id is not None and hasattr(Payment, "enrollment_id"):
        q = q.filter(Payment.enrollment_id == enrollment_id)
        return float(q.scalar() or 0.0)

    if student_id is not None and hasattr(Payment, "student_id"):
        q = q.filter(Payment.student_id == student_id)

    if course_id is not None and hasattr(Payment, "course_id"):
        q = q.filter(or_(Payment.course_id == course_id, Payment.course_id.is_(None)))

    return float(q.scalar() or 0.0)

def _enrollment_financials(en, course) -> tuple[int, int]:
    """
    خروجی: (fee, paid) برای یک ثبت‌نام.
    - اگر قسط دارد: fee/paid از اقساط
    - اگر ندارد: fee = tuition_per_student دوره، paid از Payment
    """
    if _has_installments_for_enrollment(en.id):
        fee = 0
        paid = 0
        plans = (
            InstallmentPlan.query.filter(InstallmentPlan.enrollment_id == en.id).all()
            if hasattr(InstallmentPlan, "enrollment_id")
            else []
        )
        for p in plans:
            for inst in (getattr(p, "installments", []) or []):
                fee += _inst_total(inst)
                paid += _inst_paid_amount(inst)
        return int(fee), int(paid)
    # بدون قسط
    per = _safe_num(getattr(course, "tuition_per_student", 0.0), 0.0)
    paid = _sum_paid_tuition_for(en.id if hasattr(Payment, "enrollment_id") else None,
                                 getattr(en, "student_id", None),
                                 getattr(en, "course_id", None))
    return int(per), int(paid)
def _sa_col_or_literal(model, attr_name: str, default_value=0):
    """اگر attr ستونی از نوع SQLAlchemy نبود، literal(default) بده."""
    attr = getattr(model, attr_name, None)
    return attr if isinstance(attr, InstrumentedAttribute) else literal(default_value)

def _first_existing_column(model, candidates, default_value=0):
    """اولین ستونِ واقعی را برگردان؛ در غیر اینصورت literal(default)."""
    for name in candidates:
        attr = getattr(model, name, None)
        if isinstance(attr, InstrumentedAttribute):
            return attr
    return literal(default_value)


# -------------------------------
# Finance summary (used by edit.html JS -> /mentors/<id>/finance/summary)
# -------------------------------
def _mentor_finance_summary(mentor_id: int):
    """
    Summary مالی برای یک منتور.

    items: [
      {
        course_id,
        course_title,
        students,
        fee_per_student,
        share_percent,
        income_total,   # جمع شهریه اسمی (ترکیب قسطی / غیرقسطی)
        mentor_share,   # سهم منتور از این دوره
        paid_to_mentor, # مجموع پرداخت‌های به منتور برای این دوره
        mentor_due      # بدهی باقی‌مانده برای این دوره
      }
    ]

    totals: {
      income_total,  # جمع income_total همه دوره‌ها
      share_total,   # جمع mentor_share همه دوره‌ها
      paid_total,    # مجموع پرداخت‌های EXPENSE به منتور (همه دوره‌ها)
      balance        # share_total - paid_total (>= 0)
    }
    """

    # همه‌ی دوره‌هایی که mentor_id شان این منتور است
    courses = Course.query.filter(Course.mentor_id == mentor_id).all()

    items = []
    income_total = 0
    share_total = 0

    for c in courses:
        # ثبت‌نام‌های ACTIVE همان دوره، فقط برای دانشجوهای حذف‌نشده
        enr_q = (
            Enrollment.query
            .filter(Enrollment.course_id == c.id)
        )

        # فقط وضعیت ACTIVE اگر ستون status داریم
        if hasattr(Enrollment, "status"):
            enr_q = enr_q.filter(Enrollment.status == "ACTIVE")

        # فیلتر روی Student.is_deleted اگر ستون وجود دارد
        if Student is not None and hasattr(Student, "is_deleted"):
            enr_q = (
                enr_q
                .join(Student, Enrollment.student_id == Student.id)
                .filter(or_(Student.is_deleted.is_(False),
                            Student.is_deleted.is_(None)))
            )

        enr_q = enr_q.all()
        fee_sum = 0   # جمع شهریه اسمی (برای همه ثبت‌نام‌ها)
        paid_sum = 0  # جمع دریافتی واقعی از دانشجوها (فعلاً برای گزارش‌های بعدی)

        for en in enr_q:
            fee_i, paid_i = _enrollment_financials(en, c)
            fee_sum += fee_i
            paid_sum += paid_i

        # درصد سهم منتور (بر اساس چندین نام ممکن در مدل Course)
        pct = _mentor_share_percent(c)  # مثلاً 0.3 برای 30 درصد
        share = int(round(fee_sum * pct))

        # مجموع پرداخت‌ها به منتور برای این دوره:
        # فقط kind == 'EXPENSE' (پرداخت به منتور) محاسبه می‌شود
        try:
            q = (
                db.session.query(func.coalesce(func.sum(MentorPayment.amount), 0.0))
                .filter(
                    MentorPayment.mentor_id == mentor_id,
                    MentorPayment.kind == "EXPENSE",
                )
            )
            # اگر ستون course_id وجود داشته باشد، روی همان دوره فیلتر کن
            if hasattr(MentorPayment, "course_id"):
                q = q.filter(MentorPayment.course_id == c.id)

            paid_to_mentor = float(q.scalar() or 0.0)
        except Exception:
            paid_to_mentor = 0.0

        due = max(share - int(paid_to_mentor), 0)

        items.append({
            "course_id": c.id,
            "course_title": getattr(c, "title", f"دوره #{c.id}"),
            "students": len(enr_q),

            # برای هم‌خوانی با UI:
            "fee_per_student": int(_safe_num(getattr(c, "tuition_per_student", 0), 0)),
            "share_percent": int(round(pct * 100)),

            "income_total": int(fee_sum),
            "mentor_share": int(share),
            "paid_to_mentor": int(paid_to_mentor),
            "mentor_due": int(due),
        })

        income_total += fee_sum
        share_total += share

    # مجموع پرداخت‌های به منتور (بدون تفکیک دوره، فقط EXPENSE)
    try:
        paid_total = float(
            db.session.query(func.coalesce(func.sum(MentorPayment.amount), 0.0))
            .filter(
                MentorPayment.mentor_id == mentor_id,
                MentorPayment.kind == "EXPENSE",
            )
            .scalar() or 0.0
        )
    except Exception:
        paid_total = 0.0

    balance = max(int(share_total) - int(paid_total), 0)

    return {
        "items": items,
        "totals": {
            "income_total": int(income_total),
            "share_total": int(share_total),
            "paid_total": int(paid_total),
            "balance": int(balance),
        },
    }

@bp.get("/<int:mentor_id>/finance/summary")
@login_required
def finance_summary(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    return jsonify(_mentor_finance_summary(mentor_id))


# -------------------------------
# List
# -------------------------------
@bp.get("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    query = Mentor.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Mentor.first_name.ilike(like)) |
            (Mentor.last_name.ilike(like)) |
            (Mentor.email.ilike(like)) |
            (Mentor.phone.ilike(like))
        )
    print(f"User Role: {current_user.role}")

    mentors = query.order_by(Mentor.created_at.desc()).all()
    return render_template("mentors/index.html", mentors=mentors, q=q)


# -------------------------------
# Create (GET form.html) + POST
# -------------------------------
@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_form():
    if request.method == "POST":
        f = request.form
        first = (f.get("first_name") or "").strip()
        last  = (f.get("last_name")  or "").strip()
        email = (f.get("email")      or "").strip() or None
        phone = (f.get("phone")      or "").strip() or None

        if not first or not last:
            flash("نام و نام خانوادگی الزامی است.", "error")
            return redirect(url_for("mentors.create_form"))

        # ایجاد منتور
        m = Mentor(first_name=first, last_name=last, email=email, phone=phone)
        db.session.add(m)
        db.session.flush()  # id بگیریم

        # تلاش برای ساخت حساب کاربری در صورت تیک "acc_create"
        ok, err = _attach_account_if_requested(f, m, role_name="MENTOR")
        if not ok:
            db.session.rollback()
            flash(err or "ایجاد حساب کاربری ناموفق بود.", "error")
            return redirect(url_for("mentors.create_form"))

        db.session.commit()

        # آپلود آواتار (اختیاری)
        file = request.files.get("avatar")
        if file and file.filename:
            rel = save_mentor_avatar(file, m.id)
            if rel:
                m.avatar = rel
                db.session.commit()

        flash("منتور با موفقیت ایجاد شد.", "success")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    return render_template("mentors/form.html", m=None)

# -------------------------------
# Edit (profile) – edit.html
# -------------------------------
@bp.get("/<int:mentor_id>/edit")
@login_required
def edit_form(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    taught = Course.query.filter(Course.mentor_id == m.id).order_by(Course.created_at.desc()).all()
    all_courses = Course.query.order_by(Course.created_at.desc()).all()

    # خلاصه مالی برای کارت‌های بالا
    totals = _mentor_finance_summary(m.id)["totals"]

    back_url = request.referrer or url_for("mentors.list")
    return render_template(
        "mentors/edit.html",
        m=m,
        taught=taught,
        all_courses=all_courses,
        skills_count=0,
        totals=totals,
        back_url=back_url
    )


# -------------------------------
# Update basic fields
# -------------------------------
@bp.post("/<int:mentor_id>/basic")
@login_required
def update_basic(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    f = request.form
    m.first_name = (f.get("first_name") or "").strip()
    m.last_name  = (f.get("last_name")  or "").strip()
    m.phone      = (f.get("phone")      or "").strip() or None
    m.email      = (f.get("email")      or "").strip() or None
    db.session.commit()
    flash("اطلاعات ذخیره شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))


# -------------------------------
# Upload avatar
# -------------------------------
@bp.post("/<int:mentor_id>/upload-avatar")
@login_required
def upload_avatar(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    file = request.files.get("avatar")
    if file and file.filename:
        rel = save_mentor_avatar(file, m.id)
        if rel:
            m.avatar = rel
            db.session.commit()
            flash("تصویر پروفایل به‌روزرسانی شد.", "success")
        else:
            flash("آپلود تصویر ناموفق بود.", "error")
    else:
        flash("فایلی انتخاب نشد.", "error")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))


# -------------------------------
# Assign / remove course for mentor
# -------------------------------
@bp.post("/<int:mentor_id>/courses/add")
@login_required
def add_course(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    cid = request.form.get("course_id")
    if not cid:
        flash("شناسه دوره نامعتبر است.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))
    c = Course.query.get_or_404(int(cid))
    c.mentor_id = mentor_id
    db.session.commit()
    flash("دوره به منتور نسبت داده شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))


@bp.post("/<int:mentor_id>/courses/<int:course_id>/remove")
@login_required
def remove_course(mentor_id, course_id):
    Mentor.query.get_or_404(mentor_id)
    c = Course.query.get_or_404(course_id)
    if c.mentor_id == mentor_id:
        c.mentor_id = None
        db.session.commit()
        flash("ارتباط منتور و دوره حذف شد.", "info")
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))


# -------------------------------
# Payments endpoints (AJAX)
# -------------------------------
@bp.get("/<int:mentor_id>/payments")
@login_required
def payments_list(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    payments = (
        db.session.query(MentorPayment)
        .filter(MentorPayment.mentor_id == mentor_id)
        .order_by(MentorPayment.paid_at.desc(), MentorPayment.id.desc())
        .all()
    )
    totals = _mentor_finance_summary(mentor_id)["totals"]
    items = [{
        "id": p.id,
        "amount": int(p.amount or 0),
        "kind": p.kind,
        "title": p.title or "",
        "note": p.note or "",
        "paid_at": p.paid_at.strftime("%Y-%m-%d %H:%M") if p.paid_at else "",
    } for p in payments]
    return jsonify(ok=True, items=items, totals=totals)


@bp.post("/<int:mentor_id>/payments")
@login_required
def payments_add(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    f = request.form if not request.is_json else (request.json or {})
    amount_raw = f.get("amount")
    kind   = (f.get("kind") or "EXPENSE").upper()
    title  = f.get("title")
    note   = f.get("note")

    try:
        amount = int(float(str(amount_raw).replace(",", "").replace("٬", "")))
    except Exception:
        return jsonify(ok=False, error="مبلغ نامعتبر است."), 400
    if amount <= 0:
        return jsonify(ok=False, error="مبلغ باید بیشتر از صفر باشد."), 400

    mp = MentorPayment(mentor_id=mentor_id, amount=amount, kind=kind, title=title, note=note)
    db.session.add(mp)
    db.session.commit()
    flash("پرداخت منتور ثبت شد.", "success")
    return jsonify(ok=True, id=mp.id)


@bp.delete("/<int:mentor_id>/payments/<int:pay_id>")
@login_required
def payments_delete(mentor_id, pay_id):
    Mentor.query.get_or_404(mentor_id)
    p = MentorPayment.query.filter_by(id=pay_id, mentor_id=mentor_id).first()
    if not p:
        return jsonify(ok=False, error="رکورد یافت نشد"), 404
    db.session.delete(p)
    db.session.commit()
    flash("پرداخت حذف شد.", "info")
    return jsonify(ok=True)
@bp.post("/<int:mentor_id>/account")
@login_required
def update_account(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)

    # گرفتن فیلدها از فرم
    username = (request.form.get("acc_username") or "").strip()
    email    = (request.form.get("acc_email") or "").strip()
    pw1      = request.form.get("acc_password") or ""
    pw2      = request.form.get("acc_password2") or ""

    # بررسی صحت داده‌ها
    if not username or not email:
        flash("نام کاربری و ایمیل الزامی است.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    if pw1 and pw1 != pw2:
        flash("رمز عبور و تکرار آن یکسان نیستند.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    if pw1 and len(pw1) < 6:
        flash("رمز عبور باید حداقل ۶ کاراکتر باشد.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    # چک کردن یکتایی ایمیل و نام کاربری
    u = User.query.filter_by(username=username).first()
    if u and u.id != m.user_id:
        flash("نام کاربری قبلاً استفاده شده است.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    u = User.query.filter_by(email=email).first()
    if u and u.id != m.user_id:
        flash("ایمیل قبلاً استفاده شده است.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    # اگر منتور یوزر نداشت، ایجاد می‌کنیم
    if not m.user_id:
        u = User(username=username, email=email, role="MENTOR")
        u.password_hash = generate_password_hash(pw1) if pw1 else None
        db.session.add(u)
        db.session.commit()
        m.user_id = u.id
    else:
        u = User.query.get(m.user_id)
        u.username = username
        u.email = email
        if pw1:
            u.password_hash = generate_password_hash(pw1)
        db.session.commit()

    flash("اطلاعات حساب کاربری به‌روزرسانی شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))


@bp.post("/<int:mentor_id>/delete")
@login_required
def delete(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)

    # قطع اتصال دوره‌ها از این منتور
    try:
        affected = Course.query.filter(Course.mentor_id == mentor_id).all()
        for c in affected:
            c.mentor_id = None
    except Exception:
        pass

    # Soft delete در صورت وجود ستون
    if hasattr(m, "is_deleted"):
        m.is_deleted = True
    else:
        db.session.delete(m)

    db.session.commit()
    flash("منتور حذف شد.", "info")
    return redirect(url_for("mentors.list"))
@bp.get("/me")
@login_required
def my_profile():
    m = Mentor.query.filter(
        or_(getattr(Mentor, "user_id", None) == current_user.id,
            Mentor.email == current_user.email)
    ).first()
    if not m:
        flash("پروفایل منتور پیدا نشد.", "error")
        return redirect(url_for("dashboard.index"))
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))