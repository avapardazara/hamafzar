# app/blueprints/students/routes.py
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, current_app
)
from flask_login import login_required
from sqlalchemy import or_
from ...extensions import db
from ...models.core import Student
from ...utils.files import save_student_avatar, delete_student_avatar
from flask import jsonify
from app.models.skill import Skill, StudentSkill
from app.models.course import Course
from app.models.payment import Payment
from app.models.enrollment import Enrollment
from datetime import datetime, date
bp = Blueprint("students", __name__, url_prefix="/students")



def _parse_date(s: str | None):
    if not s:
        return None
    s = s.strip().replace("/", "-")
    try:
        y, m, d = [int(x) for x in s.split("-")]
        return date(y, m, d)
    except Exception:
        return None

# ---------- Utilities ----------
def _paginate_query(base_query, page: int, per_page: int):
    total = base_query.count()
    items = (base_query
             .order_by(Student.created_at.desc())
             .offset((page - 1) * per_page)
             .limit(per_page)
             .all())
    return items, total


# ---------- List ----------
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


# ---------- Create (form) ----------
@bp.get("/new")
@login_required
def create_form():
    return render_template("students/create.html")


# ---------- Create (submit) ----------
@bp.post("/")
@login_required
def create():
    f = request.form
    first = (f.get("first_name") or "").strip()
    last = (f.get("last_name") or "").strip()

    if not first or not last:
        flash("نام و نام خانوادگی الزامی است.", "error")
        return redirect(url_for("students.create_form"))

    s = Student(
        first_name=first,
        last_name=last,
        national_code=(f.get("national_code") or "").strip() or None,
        phone=(f.get("phone") or "").strip() or None,
        email=(f.get("email") or "").strip() or None,
        address=(f.get("address") or "").strip() or None,
        notes=(f.get("notes") or "").strip() or None,
    )
    db.session.add(s)
    db.session.commit()  # تا id داشته باشه

    # آواتار (اختیاری)
    file = request.files.get("avatar")
    if file:
        rel_path = save_student_avatar(file, s.id)
        if not rel_path:
            flash("فرمت تصویر مجاز نیست یا خطایی رخ داد.", "error")
        else:
            s.avatar_path = rel_path
            db.session.commit()

    flash("کارآموز با موفقیت اضافه شد.", "success")
    return redirect(url_for("students.list"))


# ---------- Edit (form) ----------
@bp.get("/<int:student_id>/edit")
@login_required
def edit_form(student_id):
    s = Student.query.get_or_404(student_id)
    if s.is_deleted:
        flash("این رکورد حذف شده است.", "error")
        return redirect(url_for("students.list"))
    return render_template("students/edit.html", s=s)


# ---------- Update (submit) ----------
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

    # حذف تصویر؟
    delete_flag = f.get("delete_avatar")
    if delete_flag == "1" and s.avatar_path:
        delete_student_avatar(s)
        s.avatar_path = None

    # آپلود تصویر جدید؟
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


# ---------- Soft Delete ----------
@bp.post("/<int:student_id>/delete")
@login_required
def delete(student_id):
    s = Student.query.get_or_404(student_id)
    s.is_deleted = True
    db.session.commit()
    flash("رکورد حذف شد.", "info")
    return redirect(url_for("students.list"))
# ---------- Profile ----------
@bp.get("/<int:student_id>")
@login_required
def profile(student_id):
    s = Student.query.get_or_404(student_id)
    if s.is_deleted:
        flash("این کارآموز حذف شده است.", "error")
        return redirect(url_for("students.list"))

    # امن و بدون وابستگی به مدل‌های بعدی
    def safe_list(x):
        try:
            return list(x) if x else []
        except Exception:
            return []

    enrolled_courses = safe_list(getattr(s, "enrollments", []))  # بعداً واقعی می‌کنیم
    skills           = safe_list(getattr(s, "skills", []))
    payments         = safe_list(getattr(s, "payments", []))

    # ✔️ مقدار پیش‌فرض برای جلوگیری از UndefinedError
    stats = {
        "courses_count": len(enrolled_courses) if enrolled_courses else 0,
        "skills_count":  len(skills) if skills else 0,
        "balance": sum(
            (getattr(p, "amount", 0) or 0) *
            (1 if getattr(p, "type", "in") == "in" else -1)
            for p in payments
        ) if payments else 0
    }

    return render_template(
        "students/profile.html",
        s=s, stats=stats,
        enrolled_courses=enrolled_courses,
        skills=skills,
        payments=payments
    )
#مهارت های دانشجو
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
            "type": ss.skill.type,     # 'TECH' | 'SOFT'
            "name": ss.skill.name,
            "date_label": ss.date_label,
            "hours": ss.hours,
        })
    return jsonify(out), 200
#افزودن مهارت
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
        db.session.flush()  # تا skill.id داشته باشیم

    ss = StudentSkill(student_id=s.id, skill_id=skill.id,
                      date_label=date_label or None,
                      hours=int(hours) if hours else None)
    db.session.add(ss)
    db.session.commit()
    return jsonify({"ok": True, "id": ss.id}), 201
#حذف مهارت
@bp.delete("/<int:student_id>/skills/<int:ss_id>")
@login_required
def api_delete_skill(student_id, ss_id):
    s = Student.query.get_or_404(student_id)
    ss = StudentSkill.query.filter_by(id=ss_id, student_id=s.id).first_or_404()
    db.session.delete(ss)
    db.session.commit()
    return jsonify({"ok": True}), 200
#لیست ثبت نام های دانشجو
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
#افزودن ثبت نام - دوره
@bp.post("/<int:student_id>/enrollments")
@login_required
def api_add_enrollment(student_id):
    s = Student.query.get_or_404(student_id)
    data = request.get_json(silent=True) or {}
    course_id = data.get("course_id")
    status = (data.get("status") or "ONGOING").upper()

    if not course_id:
        return jsonify({"ok": False, "error": "course_required"}), 400

    # جلوگیری از ثبت‌نام تکراری
    exists = Enrollment.query.filter_by(student_id=s.id, course_id=course_id).first()
    if exists:
        return jsonify({"ok": False, "error": "already_enrolled"}), 409

    row = Enrollment(student_id=s.id, course_id=course_id, status=status)
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "id": row.id}), 201
#حذف ثبت نام دانشجو - دوره
@bp.delete("/<int:student_id>/enrollments/<int:en_id>")
@login_required
def api_delete_enrollment(student_id, en_id):
    s = Student.query.get_or_404(student_id)
    row = Enrollment.query.filter_by(id=en_id, student_id=s.id).first_or_404()
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True}), 200
#لیست سادهٔ دوره‌ها برای انتخاب (کمک به UI) - دوره
@bp.get("/courses/options")
@login_required
def api_course_options():
    q = Course.query.filter(Course.status != "ARCHIVED").order_by(Course.created_at.desc()).all()
    return jsonify([{"id": c.id, "title": c.title, "mentor_name": c.mentor_name or ""} for c in q]), 200
#افزودن تراکنش - بخش مالی - پروفایل دانشجو
@bp.get("/<int:student_id>/payments")
@login_required
def api_list_payments(student_id):
    """لیست پرداخت‌های دانشجو (Newest first)"""
    Student.query.get_or_404(student_id)  # اعتبارسنجی وجود دانشجو
    rows = (Payment.query
            .filter(Payment.student_id == student_id)
            .order_by(Payment.created_at.desc())
            .all())
    return jsonify([
        {
            "id": p.id,
            "kind": p.kind,
            "status": p.status,
            "amount": int(p.amount or 0),
            "title": p.title,
            "note": p.note,
            "course_id": getattr(p, "course_id", None),
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "due_date": p.due_date.isoformat() if p.due_date else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        } for p in rows
    ])

@bp.post("/<int:student_id>/payments")
@login_required
def api_add_payment(student_id):
    """افزودن پرداخت برای دانشجو"""
    s = Student.query.get_or_404(student_id)

    # اگر در فرم قبلاً name="type" بوده، برای سازگاری؛ ولی در DB باید kind ذخیره شود
    pkind   = (request.form.get("kind") or request.form.get("type") or "tuition").strip()
    title   = (request.form.get("title") or "").strip() or "پرداخت"
    status  = (request.form.get("status") or "paid").strip()
    amount  = int(float((request.form.get("amount") or "0").replace(",", "").replace("٬","")))

    note      = (request.form.get("note") or "").strip() or None
    paid_at_s = request.form.get("paid_at")
    due_date  = _parse_date(request.form.get("due_date"))
    course_id = request.form.get("course_id", type=int)

    row = Payment(
        student_id=s.id,
        kind=pkind,               # <-- مهم: به جای 'type'
        title=title,
        status=status,
        amount=amount,
        note=note,
        paid_at=(datetime.fromisoformat(paid_at_s) if paid_at_s else None),
        due_date=due_date,
        **({"course_id": course_id} if course_id else {})
    )

    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "id": row.id})
#حذف تراکنش - بخش مالی - پروفایل دانشجو

@bp.delete("/<int:student_id>/payments/<int:pay_id>")
@login_required
def api_delete_payment(student_id, pay_id):
    """حذف پرداخت دانشجو"""
    Student.query.get_or_404(student_id)
    p = Payment.query.filter_by(id=pay_id, student_id=student_id).first_or_404()
    db.session.delete(p)
    db.session.commit()
    return jsonify({"ok": True})