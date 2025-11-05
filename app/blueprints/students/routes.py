# app/blueprints/students/routes.py
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from flask_login import login_required,current_user  
from sqlalchemy import or_, func
from ...extensions import db
from ...models.core import Student
from ...utils.files import save_student_avatar, delete_student_avatar
from app.models.installment_plan import InstallmentPlan
from app.models.skill import Skill, StudentSkill
from app.models.course import Course
from app.models.payment import Payment
from app.models.enrollment import Enrollment
from app.models.user import User
from datetime import datetime, date
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import IntegrityError
bp = Blueprint("students", __name__, url_prefix="/students")

# ------------------------- Helpers: Payments -------------------------
def _to_ascii_digits(s: str | None) -> str:
    if not s: return ""
    return s.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))

def _digits_only(s: str | None) -> str:
    return "".join(ch for ch in _to_ascii_digits(s) if ch.isdigit())

def _normalize_national_code(s: str | None) -> str | None:
    v = _digits_only(s)
    return v or None

def _normalize_phone(s: str | None) -> str | None:
    v = _digits_only(s)
    # 98xxxxxxxxxx -> 0xxxxxxxxx
    if v.startswith("98") and len(v) == 12:
        v = "0" + v[2:]
    return v or None
def _resolve_student_for_user(u) -> Student | None:
    """با اولویت user_id سپس email دانشجو را برای کاربر جاری پیدا می‌کند."""
    # اگر ستون user_id روی مدل Student داری:
    if hasattr(Student, "user_id"):
        s = Student.query.filter_by(user_id=u.id, is_deleted=False).first()
        if s:
            return s

    # fallback با ایمیل (case-insensitive)
    email = ((getattr(u, "email", None) or "").strip().lower())
    if email:
        s = (
            Student.query
            .filter(func.lower(Student.email) == email, Student.is_deleted == False)
            .first()
        )
        if s:
            return s

    return None
def _normalize_kind(val: str) -> str:
    v = (val or "").strip().lower()
    if v in ("in", "income", "receive", "received"):
        return "receive"
    if v in ("out", "expense", "pay", "paid", "payment"):
        return "pay"
    return "receive"

def _has_attr(model, name: str) -> bool:
    return hasattr(model, name) and name in model.__table__.c

def _set_kind_fields(p: Payment, norm_kind: str):
    if _has_attr(Payment, "kind"):
        setattr(p, "kind", norm_kind)
    if _has_attr(Payment, "type"):
        setattr(p, "type", "IN" if norm_kind == "receive" else "OUT")

def _payment_is_receive_expr():
    cols = []
    if _has_attr(Payment, "kind"):
        cols.append(func.lower(Payment.kind) == "receive")
    if _has_attr(Payment, "type"):
        cols.append(func.upper(Payment.type) == "IN")
    return or_(*cols) if cols else False

def _payment_is_pay_expr():
    cols = []
    if _has_attr(Payment, "kind"):
        cols.append(func.lower(Payment.kind) == "pay")
    if _has_attr(Payment, "type"):
        cols.append(func.upper(Payment.type) == "OUT")
    return or_(*cols) if cols else False

# ------------------------- Helpers: misc -------------------------
def _attach_account_if_requested(form, person_obj, role_name="STUDENT"):
    """
    اگر کاربر در فرم تیک ساخت حساب را زده باشد، یک User با نقش role_name می‌سازیم.
    - یوزرنیم و ایمیل یکتا چک می‌شوند.
    - پسورد >= 6 و match.
    - اگر Student/Mentor ستون user_id داشته باشد، لینک می‌شود.
    """
    create_flag = (form.get("acc_create") or "") == "1"
    if not create_flag:
        return True, None  # چیزی برای انجام نیست

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

    # یکتایی
    if User.query.filter_by(username=username).first():
        return False, "این نام کاربری قبلاً ثبت شده است."
    if User.query.filter_by(email=email).first():
        return False, "این ایمیل قبلاً ثبت شده است."

    u = User(username=username, email=email, role=(role_name or "STUDENT").upper())
    u.password_hash = generate_password_hash(pw1)
    db.session.add(u)
    db.session.flush()  # تا u.id داشته باشیم

    # اگر ستون user_id روی مدل وجود داشت، لینک کن
    if hasattr(person_obj, "user_id"):
        person_obj.user_id = u.id

    return True, None
def _parse_date(s: str | None):
    if not s:
        return None
    s = s.strip().replace("/", "-")
    try:
        y, m, d = [int(x) for x in s.split("-")]
        return date(y, m, d)
    except Exception:
        return None

def _paginate_query(base_query, page: int, per_page: int):
    total = base_query.count()
    items = (
        base_query
        .order_by(Student.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return items, total

def _student_enrolled_course_ids(student_id: int) -> set[int]:
    rows = db.session.query(Enrollment.course_id).filter(Enrollment.student_id == student_id).all()
    return {int(r[0]) for r in rows}

# ------------------------- List -------------------------

@bp.get("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = 15

    query = Student.query.filter_by(is_deleted=False)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Student.first_name.ilike(like),
                Student.last_name.ilike(like),
                Student.phone.ilike(like),
                Student.national_code.ilike(like),
            )
        )

    items, total = _paginate_query(query, page, per_page)
    return render_template(
        "students/index.html",
        items=items, q=q, page=page, per_page=per_page, total=total
    )

# ------------------------- Create -------------------------

@bp.get("/new")
@login_required
def create_form():
    return render_template("students/create.html")

@bp.post("/")
@login_required
def create():
    f = request.form
    first = (f.get("first_name") or "").strip()
    last  = (f.get("last_name")  or "").strip()
    if not first or not last:
        flash("نام و نام خانوادگی الزامی است.", "error")
        return redirect(url_for("students.create_form"))

    # --- نرمال‌سازی ورودی‌ها (هلسپرها را بالای فایل داریم)
    national_code = _normalize_national_code(f.get("national_code"))
    phone         = _normalize_phone(f.get("phone"))
    email         = (f.get("email") or "").strip() or None
    address       = (f.get("address") or "").strip() or None
    notes         = (f.get("notes") or "").strip() or None

    # ---------- سناریوی احیا (restore) در صورت حذف نرم ----------
    # اولویت تطبیق: کدملی > موبایل > ایمیل
    cand = None
    if national_code:
        cand = Student.query.filter(Student.national_code == national_code).first()
    if not cand and phone:
        cand = Student.query.filter(Student.phone == phone).first()
    if not cand and email:
        cand = Student.query.filter(Student.email == email).first()

    if cand:
        if not cand.is_deleted:
            # رکورد فعال است → تکراری
            if cand.national_code == national_code and national_code:
                flash("کد ملی تکراری است.", "error")
            elif cand.phone == phone and phone:
                flash("شماره موبایل تکراری است.", "error")
            elif cand.email == email and email:
                flash("ایمیل تکراری است.", "error")
            else:
                flash("رکورد مشابهی از قبل وجود دارد.", "error")
            return redirect(url_for("students.create_form"))

        # احیا: رکورد حذف‌شده را برگردان و فیلدها را به‌روزرسانی کن
        cand.first_name    = first
        cand.last_name     = last
        cand.national_code = national_code
        cand.phone         = phone
        cand.email         = email
        cand.address       = address
        cand.notes         = notes
        cand.is_deleted    = False
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("احیای رکورد به دلیل یکتا بودن یکی از فیلدها ناموفق بود.", "error")
            return redirect(url_for("students.create_form"))

        # آپلود آواتار (اختیاری)
        file = request.files.get("avatar")
        if file:
            rel_path = save_student_avatar(file, cand.id)
            if not rel_path:
                flash("فرمت تصویر مجاز نیست یا خطایی رخ داد.", "error")
            else:
                cand.avatar_path = rel_path
                db.session.commit()

        # ساخت حساب کاربری اختیاری (اگر هلسپرش را داری)
        if "_attach_account_if_requested" in globals():
            ok, err = _attach_account_if_requested(f, cand, role_name="STUDENT")
            if not ok:
                flash(err, "error")
                return redirect(url_for("students.edit_form", student_id=cand.id))
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("ساخت حساب کاربری به دلیل تکراری بودن ایمیل/یوزرنیم انجام نشد.", "error")
                return redirect(url_for("students.edit_form", student_id=cand.id))

        flash("رکورد قبلی احیا و به‌روزرسانی شد.", "success")
        return redirect(url_for("students.profile", student_id=cand.id))

    # ---------- سناریوی ساخت رکورد جدید ----------
    # (چک یکتا برای رکوردهای فعال)
    if national_code and Student.query.filter(Student.national_code == national_code, Student.is_deleted == False).first():
        flash("کد ملی تکراری است.", "error")
        return redirect(url_for("students.create_form"))
    if phone and Student.query.filter(Student.phone == phone, Student.is_deleted == False).first():
        flash("شماره موبایل تکراری است.", "error")
        return redirect(url_for("students.create_form"))
    if email and Student.query.filter(Student.email == email, Student.is_deleted == False).first():
        flash("ایمیل تکراری است.", "error")
        return redirect(url_for("students.create_form"))

    s = Student(
        first_name=first,
        last_name=last,
        national_code=national_code,
        phone=phone,
        email=email,
        address=address,
        notes=notes,
    )
    db.session.add(s)
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        es = str(getattr(e, "orig", e))
        msg = "ثبت انجام نشد؛ یکی از فیلدهای یکتا تکراری است."
        if "students.national_code" in es: msg = "کد ملی تکراری است."
        elif "students.phone" in es:      msg = "شماره موبایل تکراری است."
        elif "students.email" in es:      msg = "ایمیل تکراری است."
        flash(msg, "error")
        return redirect(url_for("students.create_form"))

    # آواتار
    file = request.files.get("avatar")
    if file:
        rel_path = save_student_avatar(file, s.id)
        if not rel_path:
            flash("فرمت تصویر مجاز نیست یا خطایی رخ داد.", "error")
        else:
            s.avatar_path = rel_path
            db.session.commit()

    # حساب کاربری اختیاری
    if "_attach_account_if_requested" in globals():
        ok, err = _attach_account_if_requested(f, s, role_name="STUDENT")
        if not ok:
            flash(err, "error")
            return redirect(url_for("students.edit_form", student_id=s.id))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("ساخت حساب کاربری به دلیل تکراری بودن ایمیل/یوزرنیم انجام نشد.", "error")
            return redirect(url_for("students.edit_form", student_id=s.id))

    flash("کارآموز با موفقیت اضافه شد.", "success")
    return redirect(url_for("students.list"))

# ------------------------- Edit/Update -------------------------

@bp.get("/<int:student_id>/edit")
@login_required
def edit_form(student_id):
    s = Student.query.get_or_404(student_id)
    if s.is_deleted:
        flash("این رکورد حذف شده است.", "error")
        return redirect(url_for("students.list"))
    return render_template("students/edit.html", s=s)

@bp.post("/<int:student_id>")
@login_required
def update(student_id):
    s = Student.query.get_or_404(student_id)
    if s.is_deleted:
        flash("این رکورد حذف شده است.", "error")
        return redirect(url_for("students.list"))

    f = request.form
    s.first_name    = (f.get("first_name") or "").strip()
    s.last_name     = (f.get("last_name") or "").strip()
    s.national_code = (f.get("national_code") or "").strip() or None
    s.phone         = (f.get("phone") or "").strip() or None
    s.email         = (f.get("email") or "").strip() or None
    s.address       = (f.get("address") or "").strip() or None
    s.notes         = (f.get("notes") or "").strip() or None

    if not s.first_name or not s.last_name:
        flash("نام و نام خانوادگی الزامی است.", "error")
        return redirect(url_for("students.edit_form", student_id=student_id))

    delete_flag = f.get("delete_avatar")
    if delete_flag == "1" and s.avatar_path:
        delete_student_avatar(s)
        s.avatar_path = None

    file = request.files.get("avatar")
    if file:
        rel_path = save_student_avatar(file, s.id)
        if not rel_path:
            flash("فرمت تصویر مجاز نیست یا خطایی رخ داد.", "error")
        else:
            s.avatar_path = rel_path

    db.session.commit()
    flash("ویرایش با موفقیت ذخیره شد.", "success")
    return redirect(url_for("students.list"))

# ------------------------- Soft Delete -------------------------

@bp.post("/<int:student_id>/delete")
@login_required
def delete(student_id):
    s = Student.query.get_or_404(student_id)
    s.is_deleted = True
    db.session.commit()
    flash("رکورد حذف شد.", "info")
    return redirect(url_for("students.list"))

# ------------------------- Profile -------------------------

@bp.get("/<int:student_id>")
@login_required
def profile(student_id):
    s = Student.query.get_or_404(student_id)

    courses_count = db.session.query(func.count(Enrollment.id))\
        .filter(Enrollment.student_id == s.id).scalar() or 0

    skills_count = db.session.query(func.count(StudentSkill.id))\
        .filter(StudentSkill.student_id == s.id).scalar() or 0

    summary = _finance_summary(s.id)
    balance = float(summary["totals"]["balance"])

    stats = {
        "courses_count": int(courses_count),
        "skills_count": int(skills_count),
        "balance": balance,
    }
    return render_template("students/profile.html", s=s, stats=stats)

# ------------------------- Skills APIs -------------------------

@bp.get("/<int:student_id>/skills")
@login_required
def api_list_skills(student_id):
    s = Student.query.get_or_404(student_id)
    items = (
        StudentSkill.query.filter_by(student_id=s.id)
        .join(Skill, StudentSkill.skill_id == Skill.id)
        .order_by(StudentSkill.created_at.desc())
        .all()
    )
    out = []
    for ss in items:
        out.append({
            "id": ss.id,
            "type": ss.skill.type,
            "name": ss.skill.name,
            "date_label": ss.date_label,
            "hours": ss.hours,
        })
    return jsonify(out), 200

@bp.post("/<int:student_id>/skills")
@login_required
def api_add_skill(student_id):
    s = Student.query.get_or_404(student_id)
    data = request.get_json(silent=True) or {}
    stype = (data.get("type") or "").upper()
    name  = (data.get("name") or "").strip()
    date_label = (data.get("date_label") or "").strip()
    hours = data.get("hours")

    if stype not in ("TECH", "SOFT") or not name:
        return jsonify({"ok": False, "error": "invalid_input"}), 400

    skill = Skill.query.filter_by(name=name, type=stype).first()
    if not skill:
        skill = Skill(name=name, type=stype)
        db.session.add(skill)
        db.session.flush()

    ss = StudentSkill(student_id=s.id, skill_id=skill.id,
                      date_label=date_label or None,
                      hours=int(hours) if hours else None)
    db.session.add(ss)
    db.session.commit()
    return jsonify({"ok": True, "id": ss.id}), 201

@bp.delete("/<int:student_id>/skills/<int:ss_id>")
@login_required
def api_delete_skill(student_id, ss_id):
    s = Student.query.get_or_404(student_id)
    ss = StudentSkill.query.filter_by(id=ss_id, student_id=s.id).first_or_404()
    db.session.delete(ss)
    db.session.commit()
    return jsonify({"ok": True}), 200

# ------------------------- Enrollments APIs -------------------------

@bp.get("/<int:student_id>/enrollments")
@login_required
def api_list_enrollments(student_id):
    s = Student.query.get_or_404(student_id)
    rows = (
        Enrollment.query.filter_by(student_id=s.id)
        .join(Course, Enrollment.course_id == Course.id)
        .order_by(Enrollment.enrolled_at.desc())
        .all()
    )
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "status": r.status,
            "enrolled_at": r.enrolled_at.strftime("%Y-%m-%d %H:%M"),
            "course": {
                "id": r.course.id,
                "title": r.course.title,
                "mentor_name": r.course.mentor_name or ""
            }
        })
    return jsonify(out), 200

@bp.post("/<int:student_id>/enrollments")
@login_required
def api_add_enrollment(student_id):
    s = Student.query.get_or_404(student_id)
    data = request.get_json(silent=True) or {}
    course_id = data.get("course_id")
    status = (data.get("status") or "ONGOING").upper()

    if not course_id:
        return jsonify({"ok": False, "error": "course_required"}), 400

    exists = Enrollment.query.filter_by(student_id=s.id, course_id=course_id).first()
    if exists:
        return jsonify({"ok": False, "error": "already_enrolled"}), 409

    row = Enrollment(student_id=s.id, course_id=course_id, status=status)
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "id": row.id}), 201

@bp.delete("/<int:student_id>/enrollments/<int:en_id>")
@login_required
def api_delete_enrollment(student_id, en_id):
    s = Student.query.get_or_404(student_id)
    row = Enrollment.query.filter_by(id=en_id, student_id=s.id).first_or_404()
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True}), 200

# ----- course options for general use (all active courses)
@bp.get("/courses/options")
@login_required
def api_course_options():
    q = Course.query.filter(Course.status != "ARCHIVED").order_by(Course.created_at.desc()).all()
    return jsonify([{"id": c.id, "title": c.title, "mentor_name": c.mentor_name or ""} for c in q]), 200

# ----- NEW: course options limited to the student's enrollments (for finance select)
@bp.get("/<int:student_id>/courses/enrolled-options")
@login_required
def api_enrolled_course_options(student_id):
    Student.query.get_or_404(student_id)
    rows = (
        db.session.query(Course.id, Course.title, Course.mentor_name)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .filter(Enrollment.student_id == student_id)
        .order_by(Course.created_at.desc())
        .all()
    )
    return jsonify([{"id": r.id, "title": r.title, "mentor_name": r.mentor_name or ""} for r in rows]), 200

# ------------------------- Payments APIs -------------------------

@bp.get("/<int:student_id>/payments")
@login_required
def api_list_payments(student_id):
    Student.query.get_or_404(student_id)
    q = Payment.query.filter(Payment.student_id == student_id).order_by(Payment.id.desc())

    items = []
    for p in q.all():
        if _has_attr(Payment, "type"):
            t = getattr(p, "type") or ("IN" if getattr(p, "kind", "") == "receive" else "OUT")
        else:
            t = "IN" if (getattr(p, "kind", "") or "").lower() == "receive" else "OUT"

        created_label = ""
        if _has_attr(Payment, "created_at") and getattr(p, "created_at"):
            created_label = getattr(p, "created_at").strftime("%Y-%m-%d")

        items.append({
            "id": p.id,
            "title": p.title,
            "amount": p.amount,
            "type": t,
            "created_at": created_label
        })

    total_in = db.session.query(func.coalesce(func.sum(Payment.amount), 0))\
        .filter(Payment.student_id == student_id, _payment_is_receive_expr()).scalar() or 0
    total_out = db.session.query(func.coalesce(func.sum(Payment.amount), 0))\
        .filter(Payment.student_id == student_id, _payment_is_pay_expr()).scalar() or 0
    balance = int(total_in) - int(total_out)

    return jsonify(items=items, balance=balance)

@bp.post("/<int:student_id>/payments")
@login_required
def api_add_payment(student_id):
    s = Student.query.get_or_404(student_id)

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    amount = data.get("amount")
    raw_kind = data.get("type") or data.get("kind") or "IN"
    course_id = data.get("course_id")

    if not title:
        return jsonify(error="عنوان الزامی است."), 400
    try:
        amount = int(amount)
    except Exception:
        return jsonify(error="مبلغ نامعتبر است."), 400
    if amount <= 0:
        return jsonify(error="مبلغ باید بزرگتر از صفر باشد."), 400

    kind = _normalize_kind(raw_kind)

    p = Payment()
    p.student_id = s.id

    # اگر کاربر دوره‌ای را انتخاب کرده، باید واقعاً دانشجو در آن ثبت‌نام شده باشد
    if course_id not in (None, "", 0):
        try:
            cid = int(course_id)
        except Exception:
            return jsonify(error="شناسه دوره نامعتبر است."), 400

        # وجود دوره
        c = Course.query.get(cid)
        if not c:
            return jsonify(error="دوره یافت نشد."), 404

        # اعتبارسنجی ثبت‌نام دانشجو در همان دوره
        enrolled_ids = _student_enrolled_course_ids(s.id)
        if cid not in enrolled_ids:
            return jsonify(error="دانشجو در این دوره ثبت‌نام نشده است."), 400

        p.course_id = cid

    p.title = title
    p.amount = amount
    _set_kind_fields(p, kind)
    if _has_attr(Payment, "created_at") and getattr(p, "created_at") is None:
        p.created_at = datetime.utcnow()

    db.session.add(p)
    db.session.commit()
    return jsonify(ok=True, id=p.id)

@bp.delete("/<int:student_id>/payments/<int:pay_id>")
@login_required
def api_delete_payment(student_id, pay_id):
    Student.query.get_or_404(student_id)
    p = Payment.query.filter_by(id=pay_id, student_id=student_id).first_or_404()
    db.session.delete(p)
    db.session.commit()
    return jsonify(ok=True)

# ------------------------- Finance Summary (no SQL over @property) -------------------------

def _get_course_fee(course_obj) -> int:
    for attr in ("fee_per_student", "fee", "price_per_student", "price", "tuition"):
        if hasattr(course_obj, attr):
            try:
                val = getattr(course_obj, attr)
                if val is not None:
                    return int(val) or 0
            except Exception:
                pass
    return 0

def _finance_summary(student_id: int):
    rows = (
        db.session.query(Enrollment.course_id, Course.title, Course)
        .join(Course, Course.id == Enrollment.course_id)
        .filter(Enrollment.student_id == student_id)
        .order_by(Enrollment.course_id)
        .all()
    )

    items = []
    total_fee = 0
    total_paid = 0

    for course_id, course_title, course_obj in rows:
        fee = _get_course_fee(course_obj)

        paid = (
            db.session.query(func.coalesce(func.sum(Payment.amount), 0))
            .filter(
                Payment.student_id == student_id,
                Payment.course_id == course_id,
                _payment_is_receive_expr()
            )
            .scalar()
            or 0
        )

        items.append({
            "course_id": int(course_id),
            "course_title": course_title,
            "fee": int(fee),
            "paid": int(paid),
            "balance": int(fee) - int(paid),
        })

        total_fee += int(fee)
        total_paid += int(paid)

    return {
        "items": items,
        "totals": {
            "fee": int(total_fee),
            "paid": int(total_paid),
            "balance": int(total_fee) - int(total_paid),
        }
    }

@bp.get("/<int:student_id>/finance/summary")
@login_required
def finance_summary(student_id: int):
    s = Student.query.get_or_404(student_id)

    # همهٔ ثبت‌نام‌های دانشجو + عنوان و آبجکت Course (برای استخراج شهریه)
    enroll_rows = (
        db.session.query(Enrollment.course_id, Course.title, Course)
        .join(Course, Course.id == Enrollment.course_id)
        .filter(Enrollment.student_id == s.id)
        .all()
    )

    course_titles = {}
    course_fees = {}
    for cid, ctitle, cobj in enroll_rows:
        cid = int(cid)
        course_titles[cid] = ctitle
        course_fees[cid] = _get_course_fee(cobj)

    # همهٔ برنامه‌های قسط مرتبط با دانشجو (مستقیم/از طریق enrollment)
    student_en_ids = db.session.query(Enrollment.id).filter(Enrollment.student_id == s.id).subquery()
    plans = (
        InstallmentPlan.query
        .filter(or_(
            InstallmentPlan.student_id == s.id,
            InstallmentPlan.enrollment_id.in_(student_en_ids)
        ))
        .all()
    )

    # per: تجمیع مالی دوره‌هایی که «قسط دارند» (منبع واحد = اقساط)
    per = {}
    for p in plans:
        cid = getattr(p, "course_id", None)
        if not cid and getattr(p, "enrollment_id", None):
            en = Enrollment.query.get(p.enrollment_id)
            cid = en.course_id if en else None
        if not cid:
            continue
        cid = int(cid)
        title = course_titles.get(cid, "—")
        insts = p.installments or []
        total = sum(int(i.amount_total or 0) for i in insts)
        paid = sum(int(i.amount_total or 0) for i in insts if ((i.status or "").upper() == "PAID"))
        if cid not in per:
            per[cid] = {"course_id": cid, "course_title": title, "fee": 0, "paid": 0}
        per[cid]["fee"] += total
        per[cid]["paid"] += paid

    items = []
    total_balance = 0

    # 1) دوره‌های دارای قسط
    has_plan_courses = set([k for k in per.keys() if k is not None])
    for cid, v in per.items():
        bal = max(int(v["fee"]) - int(v["paid"]), 0)
        row = dict(v, balance=int(bal))
        items.append(row)
        total_balance += bal

    # 2) دوره‌های بدون قسط → شهریهٔ دوره + جمع دریافتی‌های نقدی همان دوره (DB-side)
    no_plan_course_ids = [cid for cid in course_titles.keys() if cid not in has_plan_courses]
    if no_plan_course_ids:
        pay_rows = (
            db.session.query(
                Payment.course_id,
                func.coalesce(func.sum(Payment.amount), 0).label("sum_in"),
            )
            .filter(
                Payment.student_id == s.id,
                Payment.course_id.in_(no_plan_course_ids),
                _payment_is_receive_expr(),
            )
            .group_by(Payment.course_id)
            .all()
        )
        paid_map = {int(cid or 0): int(amount or 0) for cid, amount in pay_rows}

        for cid in no_plan_course_ids:
            fee = int(course_fees.get(cid, 0))
            paid = int(paid_map.get(cid, 0))
            bal = max(fee - paid, 0)
            items.append({
                "course_id": cid,
                "course_title": course_titles.get(cid, "—"),
                "fee": fee,
                "paid": paid,
                "balance": bal,
            })
            total_balance += bal

    # مرتب‌سازی: بیشترین مانده اول
    items.sort(key=lambda x: (-int(x["balance"]), x["course_title"] or ""))
    return jsonify({"items": items, "totals": {"balance": int(total_balance)}})

@bp.get("/<int:student_id>/finance/installments")
@login_required
def finance_installments(student_id: int):
    # وجود دانشجو
    Student.query.get_or_404(student_id)

    # همه‌ی Enrollmentهای دانشجو
    student_en_ids = (
        db.session.query(Enrollment.id)
        .filter(Enrollment.student_id == student_id)
        .subquery()
    )

    # همه‌ی برنامه‌های قسط مربوط به دانشجو (مستقیم/غیرمستقیم)
    plans = (
        InstallmentPlan.query
        .filter(or_(
            InstallmentPlan.student_id == student_id,
            InstallmentPlan.enrollment_id.in_(student_en_ids)
        ))
        .all()
    )

    items = []
    for p in plans:
        # course_id ایمن
        cid = getattr(p, "course_id", None)
        if not cid and getattr(p, "enrollment_id", None):
            en = Enrollment.query.get(p.enrollment_id)
            cid = en.course_id if en else None

        # عنوان دوره
        course_title = "—"
        if cid:
            c = Course.query.get(cid)
            if c:
                course_title = c.title

        # اقساط
        for inst in (p.installments or []):
            items.append({
                "plan_id": p.id,
                "plan_title": p.title or "",
                "course_title": course_title,
                "seq": inst.seq,
                "due_date": (inst.due_date.isoformat() if getattr(inst, "due_date", None) else None),
                "amount_total": int(inst.amount_total or 0),
                "amount_base": int(inst.amount_base or 0),
                "cheque_fee_amount": int(inst.cheque_fee_amount or 0),
                "status": (inst.status or "PENDING"),
            })

    # مرتب‌سازی: سررسید (خالی‌ها آخر) سپس شماره قسط
    items.sort(key=lambda x: (x["due_date"] is None, x["due_date"] or "", x["seq"] or 0))
    return jsonify({"items": items})
@bp.get("/me")
@login_required
def me():
    """پروفایل من (دانشجو): کاربر جاری را به /students/<id> ریدایرکت می‌کند."""
    s = _resolve_student_for_user(current_user)
    if not s:
        from flask import flash, redirect, url_for
        flash("برای حساب شما پروفایل دانشجویی پیدا نشد.", "error")
        # ادمین را برگردان به لیست دانشجوها، سایرین به داشبورد
        role = ((current_user.role or "").upper())
        return redirect(url_for("students.list") if role == "ADMIN" else url_for("dashboard.index"))
    from flask import redirect, url_for
    return redirect(url_for("students.profile", student_id=s.id))