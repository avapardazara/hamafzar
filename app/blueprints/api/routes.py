from datetime import datetime, date

from flask import jsonify, g, request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy import or_, func, case

from . import api_bp
from app.security.tokens import api_auth_required
from app.extensions import db

from app.models.core import Student
from app.models.mentor import Mentor
from app.models.course import Course

from app.utils.files import save_mentor_avatar
from app.utils.files import save_course_cover, delete_course_cover
from app.blueprints.mentors.routes import _attach_account_if_requested
from app.models.mentor_payment import MentorPayment
from app.models.course_session import CourseSession, Attendance

from app.models.installment_plan import InstallmentPlan
from app.models.installment import Installment
from app.models.installment_cheque import InstallmentCheque

from app.models.skill import Skill, StudentSkill

from app.models.payment import Payment
from app.models.enrollment import Enrollment
from app.blueprints.finance.routes import _enrollment_financials



from app.blueprints.courses.routes import (
    _validate_schedule_inputs_for,
    _norm_dates_str_list,
    _generate_dates_weekly,
)

try:
    from app.models.enrollment import Enrollment
except ImportError:  # اگر فعلاً نداری، بعداً پرش می‌کنیم
    Enrollment = None
try:
    from app.models.course_session import SessionFile
except Exception:
    SessionFile = None


#----------------------HELPER------------------------------

def _payment_to_dict_api(p: Payment, course: Course | None = None) -> dict:
    """خروجی استاندارد برای Payment در API دانشجو."""
    if not p:
        return {}

    if course is None and getattr(p, "course_id", None):
        try:
            course = Course.query.get(p.course_id)
        except Exception:
            course = None

    amount = getattr(p, "amount", 0.0) or 0.0
    kind = (getattr(p, "kind", None) or "").lower()
    status = (getattr(p, "status", None) or "").lower()

    # نوع برای UI (IN/OUT)
    direction = "IN"
    if kind in ("refund", "expense") or amount < 0:
        direction = "OUT"

    def _dt_to_str(v):
        if isinstance(v, (datetime, date)):
            try:
                return v.isoformat()
            except Exception:
                return None
        return None

    return {
        "id": getattr(p, "id", None),
        "title": getattr(p, "title", None),
        "note": getattr(p, "note", None),
        "kind": getattr(p, "kind", None),
        "status": getattr(p, "status", None),
        "type": direction,  # برای فرانت همین رو می‌خوان
        "amount": int(amount),
        "course_id": getattr(p, "course_id", None),
        "course_title": getattr(course, "title", None) if course else None,
        "paid_at": _dt_to_str(getattr(p, "paid_at", None)),
        "created_at": _dt_to_str(getattr(p, "created_at", None)),
    }

# -------------------------------------------------
# ✅ fallback uploader (چون save_uploaded_file در پروژه نیست)
# -------------------------------------------------
import os
from werkzeug.utils import secure_filename
from flask import current_app

def save_uploaded_file(file, subdir="sessions"):
    """
    فایل را در uploads/<subdir>/ ذخیره می‌کند
    خروجی: مسیر نسبی برای ذخیره روی DB
    """
    if not file or not getattr(file, "filename", ""):
        return None

    filename = secure_filename(file.filename)

    uploads_root = os.path.join(current_app.root_path, "..", "uploads")
    target_dir = os.path.join(uploads_root, subdir)
    os.makedirs(target_dir, exist_ok=True)

    abs_path = os.path.join(target_dir, filename)
    file.save(abs_path)

    rel_path = f"{subdir}/{filename}".replace("\\", "/")
    return rel_path

def _student_brief(st: Student) -> dict:
    """خلاصه اطلاعات دانشجو برای JSON"""
    full_name = getattr(st, "full_name", None)
    if not full_name:
        full_name = f"{(st.first_name or '').strip()} {(st.last_name or '').strip()}".strip() or "—"

    return {
        "id": st.id,
        "full_name": full_name,
        "phone": getattr(st, "phone", None),
        "code": getattr(st, "student_code", None),
        "major": getattr(st, "major", None),
        "is_deleted": getattr(st, "is_deleted", False),
    }

# =========================
# ✅ Global OPTIONS handler (CORS preflight)
# =========================
@api_bp.route("/<path:_path>", methods=["OPTIONS"])
def api_options_passthrough(_path):
    """
    برای اینکه هیچ preflight ای 404 نخوره.
    مرورگر قبل از درخواست واقعی، OPTIONS می‌زنه و باید 200 بگیره.
    """
    return jsonify({"ok": True}), 200
#---------------financeHelpers-------------------
def session_to_dict(s: CourseSession, stats: dict | None = None) -> dict:
    """خروجی استاندارد جلسه برای فرانت (همون چیزی که تو تب Sessions و صفحه جزئیات استفاده می‌کنیم)."""
    stats = stats or {}

    # تاریخ جلسه: هر ستونی که داری، یکی رو برمی‌داریم
    session_date = (
        getattr(s, "session_date", None)
        or getattr(s, "date", None)
        or getattr(s, "date_gregorian", None)
        or getattr(s, "date_jalali", None)
    )

    try:
        if hasattr(session_date, "isoformat"):
            session_date = session_date.isoformat()
    except Exception:
        session_date = str(session_date) if session_date is not None else None

    # 🔹 موضوع و توضیحات از مدل CourseSession
    topic = getattr(s, "topic", None)
    description = getattr(s, "description", None)

    return {
        "id": getattr(s, "id", None),
        "course_id": getattr(s, "course_id", None),
        "session_date": session_date,
        "start_time": getattr(s, "start_time", None),
        "end_time": getattr(s, "end_time", None),
        "duration_minutes": getattr(s, "duration_minutes", None),
        "status": getattr(s, "status", None) or "PLANNED",
        "topic": topic,
        "description": description,
        "stats": {
            "total": stats.get("total", 0),
            "present": stats.get("present", 0),
            "absent": stats.get("absent", 0),
        },
    }


def _parse_date_field(value):
    """
    رشته YYYY-MM-DD رو به date تبدیل می‌کند.
    اگر خالی یا نامعتبر باشد -> None
    """
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None

# ---------- Health ----------

@api_bp.route("/health", methods=["GET"])
def api_health():
    # بدون نیاز به توکن – برای تست Proxy/اتصال
    return jsonify({"ok": True, "service": "ham-afzar-api"})


# ---------- Helper: Course → dict ----------

def course_to_dict(c: Course) -> dict:
    if not c:
        return {}

    # mentor_name شبیه قالب‌های قبلی
    mentor_name = getattr(c, "mentor_name", None)
    mentor = getattr(c, "mentor", None)
    if not mentor_name and mentor is not None:
        full = getattr(mentor, "full_name", None)
        if not full:
            first = getattr(mentor, "first_name", "") or ""
            last = getattr(mentor, "last_name", "") or ""
            full = f"{first} {last}".strip() or None
        mentor_name = full

    # کاور دوره
    cover_rel = getattr(c, "cover_image", None) or getattr(c, "cover_path", None)
    cover_url = None
    if cover_rel:
        try:
            from flask import url_for
            cover_url = url_for("uploaded_file", filename=cover_rel, _external=False)
        except Exception:
            cover_url = f"/uploads/{cover_rel}"

    created_at = getattr(c, "created_at", None)
    if created_at is not None:
        try:
            created_at = created_at.isoformat()
        except Exception:
            created_at = str(created_at)

    return {
        "id": getattr(c, "id", None),
        "title": getattr(c, "title", None),
        "mentor_id": getattr(c, "mentor_id", None),
        "mentor_name": mentor_name,
        "status": getattr(c, "status", None) or "ACTIVE",

        "category": getattr(c, "category", None),
        "level": getattr(c, "level", None),
        "capacity": getattr(c, "capacity", None),

        "start_date": getattr(c, "start_date", None),
        "end_date": getattr(c, "end_date", None),
        "start_time": getattr(c, "start_time", None),
        "end_time": getattr(c, "end_time", None),

        "fee_per_student": getattr(c, "fee_per_student", None),
        "mentor_share_percent": getattr(c, "mentor_share_percent", None),

        "schedule_type": getattr(c, "schedule_type", None),
        "schedule_days": getattr(c, "schedule_days", None),
        "schedule_pattern": getattr(c, "schedule_pattern", None),
        "weekly_days_json": getattr(c, "weekly_days_json", None),
        "sessions_json": getattr(c, "sessions_json", None),

        "cover_image": cover_rel,
        "cover_url": cover_url,

        "created_at": created_at,
    }


# ---------- Me (کاربر فعلی بر اساس توکن API) ----------

@api_bp.route("/me", methods=["GET"])
@api_auth_required()  # هر نقش تایید شود
def api_me():
    u = getattr(g, "api_user", None)
    if not u:
        return jsonify({"error": "unauthorized"}), 401

    # تلاش برای نقش واحد/لیست
    role = getattr(u, "role", None)
    if not role and hasattr(u, "roles"):
        try:
            role = next(iter([getattr(r, "name", str(r)) for r in u.roles]), None)
        except Exception:
            role = None

    return jsonify(
        {
            "id": getattr(u, "id", None),
            "name": getattr(u, "name", None) or getattr(u, "full_name", None),
            "email": getattr(u, "email", None),
            "role": (role or "student"),
        }
    )


# ---------- Helper: تبدیل رشته تاریخ به date پایتونی ----------

def _parse_date(value):
    """
    ورودی: رشته YYYY-MM-DD
    خروجی: date یا None
    """
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except Exception:
        return None


# ======================================================
# Students API
# ======================================================

@api_bp.get("/students")
@api_auth_required()
def api_students_list():
    """
    لیست دانشجوها برای فرانت Nuxt
    GET /api/students?q=...&date_from=1402-01-01&date_to=1402-12-29
    """
    q = (request.args.get("q") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()

    query = Student.query.filter_by(is_deleted=False)

    # فیلتر جست‌وجو
    if q:
        like = f"%{q}%"
        query = query.filter(
            Student.full_name.ilike(like) |
            Student.first_name.ilike(like) |
            Student.last_name.ilike(like) |
            Student.phone.ilike(like) |
            Student.national_code.ilike(like) |
            Student.email.ilike(like)
        )

    # TODO: اگر ستون تاریخ ثبت‌نام داری، اینجا فیلتر تاریخ رو اضافه کن

    students = query.order_by(Student.id.desc()).all()

    def to_dict(s: Student):
        return {
            "id": s.id,
            "full_name": getattr(s, "full_name", None)
                         or f"{getattr(s, 'first_name', '')} {getattr(s, 'last_name', '')}".strip() or None,
            "first_name": getattr(s, "first_name", None),
            "last_name": getattr(s, "last_name", None),
            "phone": getattr(s, "phone", None),
            "national_code": getattr(s, "national_code", None),
            "email": getattr(s, "email", None),
            "avatar_url": getattr(s, "avatar_url", None),
            "created_at": getattr(s, "created_at", None).isoformat() if getattr(s, "created_at", None) else None,
        }

    items = [to_dict(s) for s in students]
    total = len(items)

    return jsonify({
        "items": items,
        "students": items,
        "total": total,
    })


@api_bp.get("/students/<int:student_id>")
@api_auth_required()
def api_student_detail(student_id: int):
    """
    پروفایل دانشجو + لیست دوره‌های ثبت‌نام‌شده
    GET /api/students/<id>
    """
    s = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    # اطلاعات اصلی
    full_name = getattr(s, "full_name", None)
    if not full_name:
        full_name = f"{(s.first_name or '').strip()} {(s.last_name or '').strip()}".strip() or None

    data = {
        "id": s.id,
        "full_name": full_name,
        "first_name": getattr(s, "first_name", None),
        "last_name": getattr(s, "last_name", None),
        "phone": getattr(s, "phone", None),
        "national_code": getattr(s, "national_code", None),
        "email": getattr(s, "email", None),
        "avatar_url": getattr(s, "avatar_url", None),
        "created_at": getattr(s, "created_at", None).isoformat() if getattr(s, "created_at", None) else None,
    }

    # ---- لیست ثبت‌نام‌ها (دوره‌های دانشجو) ----
    enrollments_payload = []
    if Enrollment is not None:
        enrs = (
            Enrollment.query
            .filter_by(student_id=student_id)
            .all()
        )
        for e in enrs:
            course = getattr(e, "course", None)
            mentor_name = None
            if course is not None:
                mentor = getattr(course, "mentor", None)
                if mentor is not None:
                    mentor_name = (
                        getattr(mentor, "full_name", None)
                        or f"{(getattr(mentor, 'first_name', '') or '').strip()} "
                           f"{(getattr(mentor, 'last_name', '') or '').strip()}".strip()
                        or None
                    )

            enrollments_payload.append({
                "id": e.id,
                "course_id": getattr(e, "course_id", None),
                "course_title": getattr(course, "title", None) if course else None,
                "status": getattr(e, "status", None) or "ACTIVE",
                "mentor_name": mentor_name,
                "enrolled_at": getattr(e, "enrolled_at", None).isoformat()
                               if getattr(e, "enrolled_at", None) else None,
                "joined_at": getattr(e, "joined_at", None).isoformat()
                             if getattr(e, "joined_at", None) else None,
            })

    data["enrollments"] = enrollments_payload
    # فعلاً پرداخت و اقساط خالی می‌مانند تا بعداً وصلشان کنیم
    data["payments"] = []
    data["instalments"] = []

    return jsonify(data)

@api_bp.post("/students")
@api_auth_required()
def api_student_create():
    """
    ساخت دانشجوی جدید
    POST /api/students
    """
    data = request.get_json(silent=True) or {}

    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    if not first_name or not last_name:
        return jsonify({"error": "نام و نام خانوادگی الزامی است"}), 400

    student = Student(
        first_name=first_name,
        last_name=last_name,
        national_code=(data.get("national_code") or "").strip() or None,
        phone=(data.get("phone") or data.get("mobile") or "").strip() or None,
        email=(data.get("email") or "").strip() or None,
        address=(data.get("address") or "").strip() or None,
        notes=data.get("note") or data.get("notes") or None,
    )

    db.session.add(student)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "دانشجویی با این کد ملی یا شماره تلفن قبلاً ثبت شده است"
        }), 400

    result = {
        "id": student.id,
        "full_name": student.full_name,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "phone": student.phone,
        "national_code": student.national_code,
        "email": student.email,
        "avatar_url": getattr(student, "avatar_url", None),
        "created_at": student.created_at.isoformat() if student.created_at else None,
    }

    return jsonify(result), 201


@api_bp.put("/students/<int:student_id>")
@api_auth_required()
def api_student_update(student_id: int):
    """
    ویرایش دانشجو
    PUT /api/students/<id>
    """
    student = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    data = request.get_json(silent=True) or {}

    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    if not first_name or not last_name:
        return jsonify({"error": "نام و نام خانوادگی الزامی است"}), 400

    student.first_name = first_name
    student.last_name = last_name
    student.national_code = (data.get("national_code") or "").strip() or None
    student.phone = (data.get("phone") or data.get("mobile") or "").strip() or None
    student.email = (data.get("email") or "").strip() or None
    student.address = (data.get("address") or "").strip() or None
    student.notes = data.get("note") or data.get("notes") or None

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "دانشجویی با این کد ملی یا شماره تلفن قبلاً ثبت شده است"
        }), 400

    result = {
        "id": student.id,
        "full_name": student.full_name,
        "first_name": student.first_name,
        "last_name": student.last_name,
        "phone": student.phone,
        "national_code": student.national_code,
        "email": student.email,
        "avatar_url": getattr(student, "avatar_url", None),
        "created_at": student.created_at.isoformat() if student.created_at else None,
    }

    return jsonify(result), 200


@api_bp.delete("/students/<int:student_id>")
@api_auth_required()
def api_student_delete(student_id: int):
    """
    حذف نرم دانشجو
    DELETE /api/students/<id>
    """
    student = Student.query.get_or_404(student_id)

    if student.is_deleted:
        return jsonify({"ok": True}), 200

    student.is_deleted = True
    db.session.commit()

    return jsonify({"ok": True}), 200


# ======================================================
# Mentors API
# ======================================================

def mentor_to_dict(m: Mentor) -> dict:
    """
    خروجی استاندارد منتور برای فرانت.
    """
    if not m:
        return {}

    full_name = getattr(m, "full_name", None)
    if not full_name:
        first = getattr(m, "first_name", "") or ""
        last = getattr(m, "last_name", "") or ""
        full_name = f"{first} {last}".strip() or None

    avatar_path = getattr(m, "avatar_path", None) or getattr(m, "avatar", None)
    avatar_url = getattr(m, "avatar_url", None)

    result = {
        "id": m.id,
        "full_name": full_name,
        "first_name": getattr(m, "first_name", None),
        "last_name": getattr(m, "last_name", None),
        "email": getattr(m, "email", None),
        "phone": getattr(m, "phone", None),
        "expertise": getattr(m, "expertise", None),
        "status": getattr(m, "status", None),
        "avatar_path": avatar_path,
        "avatar_url": avatar_url,
        "created_at": m.created_at.isoformat() if getattr(m, "created_at", None) else None,
    }

    for extra in ("national_code", "address", "bio", "note"):
        if hasattr(m, extra):
            result[extra] = getattr(m, extra)

    return result


def mentor_payment_to_dict(p: MentorPayment) -> dict:
    """خروجی استاندارد یک تراکنش مالی منتور برای فرانت Nuxt."""
    mentor = getattr(p, "mentor", None)
    mentor_name = None
    if mentor is not None:
        mentor_name = getattr(mentor, "full_name", None)
        if not mentor_name:
            first = getattr(mentor, "first_name", "") or ""
            last = getattr(mentor, "last_name", "") or ""
            mentor_name = f"{first} {last}".strip() or None

    return {
        "id": p.id,
        "mentor_id": p.mentor_id,
        "amount": p.amount,
        "kind": p.kind,  # 'INCOME' یا 'EXPENSE'
        "title": p.title,
        "note": p.note,
        "paid_at": p.paid_at.isoformat() if getattr(p, "paid_at", None) else None,
        "mentor_name": mentor_name,
    }



@api_bp.get("/mentors")
@api_auth_required()
def api_mentors_list():
    """
    لیست منتورها
    GET /api/mentors?q=...&status=...
    """
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().lower()

    query = Mentor.query

    if hasattr(Mentor, "is_deleted"):
        query = query.filter(Mentor.is_deleted.is_(False))

    if q:
        like = f"%{q}%"
        conditions = []
        for field in ("first_name", "last_name", "email", "phone", "expertise"):
            col = getattr(Mentor, field, None)
            if isinstance(col, InstrumentedAttribute):
                conditions.append(col.ilike(like))
        if conditions:
            query = query.filter(or_(*conditions))

    if status and hasattr(Mentor, "status"):
        query = query.filter(Mentor.status == status)

    mentors = query.order_by(
        getattr(Mentor, "created_at", getattr(Mentor, "id")).desc()
    ).all()

    items = [mentor_to_dict(m) for m in mentors]
    total = len(items)

    return jsonify({
        "items": items,
        "mentors": items,
        "total": total,
    })


@api_bp.get("/mentors/<int:mentor_id>")
@api_auth_required()
def api_mentor_detail(mentor_id: int):
    """
    جزئیات یک منتور
    GET /api/mentors/<id>
    """
    query = Mentor.query
    if hasattr(Mentor, "is_deleted"):
        query = query.filter(Mentor.is_deleted.is_(False))

    m = query.filter(Mentor.id == mentor_id).first_or_404()

    mentor_data = mentor_to_dict(m)

    stats = {
        "courses_count": 0,
        "skills_count": 0,
        "balance": 0,
    }
    finance = {
        "totals": {
            "balance": 0,
            "installments_active": 0,
            "paid": 0,
        },
        "items": [],
    }
    courses = []

    return jsonify({
        "mentor": mentor_data,
        "stats": stats,
        "finance": finance,
        "courses": courses,
    }), 200


@api_bp.post("/mentors")
@api_auth_required()
def api_mentor_create():
    """
    ساخت منتور جدید (multipart/form-data)
    """
    form = request.form or {}
    first_name = (form.get("first_name") or "").strip()
    last_name = (form.get("last_name") or "").strip()

    if not first_name or not last_name:
        return jsonify({"error": "نام و نام خانوادگی منتور الزامی است."}), 400

    mentor = Mentor(
        first_name=first_name,
        last_name=last_name,
    )

    if hasattr(Mentor, "email"):
        mentor.email = (form.get("email") or "").strip() or None
    if hasattr(Mentor, "phone"):
        mentor.phone = (form.get("phone") or "").strip() or None
    if hasattr(Mentor, "expertise"):
        mentor.expertise = (form.get("expertise") or "").strip() or None
    if hasattr(Mentor, "status") and form.get("status"):
        mentor.status = form.get("status")

    for extra in ("national_code", "address", "bio", "note"):
        if hasattr(Mentor, extra) and extra in form:
            setattr(mentor, extra, form.get(extra) or None)

    db.session.add(mentor)
    db.session.flush()

    avatar_file = request.files.get("avatar")
    if avatar_file:
        rel_path = save_mentor_avatar(avatar_file, mentor.id)
        if rel_path:
            if hasattr(mentor, "avatar_path"):
                mentor.avatar_path = rel_path
            elif hasattr(mentor, "avatar"):
                mentor.avatar = rel_path

    ok, msg = _attach_account_if_requested(form, mentor, role_name="MENTOR")
    if not ok:
        db.session.rollback()
        return jsonify({"error": msg}), 400

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "خطای یکتا بودن داده‌ها (مثل ایمیل تکراری)."}), 400

    return jsonify(mentor_to_dict(mentor)), 201


@api_bp.put("/mentors/<int:mentor_id>")
@api_auth_required()
def api_mentor_update(mentor_id: int):
    """
    ویرایش منتور (multipart/form-data)
    """
    form = request.form or {}

    mentor = Mentor.query.get_or_404(mentor_id)
    if hasattr(Mentor, "is_deleted") and getattr(mentor, "is_deleted", False):
        return jsonify({"error": "این منتور حذف شده است."}), 404

    if "first_name" in form:
        mentor.first_name = (form.get("first_name") or "").strip()
    if "last_name" in form:
        mentor.last_name = (form.get("last_name") or "").strip()
    if hasattr(Mentor, "email") and "email" in form:
        mentor.email = (form.get("email") or "").strip() or None
    if hasattr(Mentor, "phone") and "phone" in form:
        mentor.phone = (form.get("phone") or "").strip() or None
    if hasattr(Mentor, "expertise") and "expertise" in form:
        mentor.expertise = (form.get("expertise") or "").strip() or None
    if hasattr(Mentor, "status") and "status" in form:
        mentor.status = form.get("status") or None

    for extra in ("national_code", "address", "bio", "note"):
        if hasattr(Mentor, extra) and extra in form:
            setattr(mentor, extra, form.get(extra) or None)

    avatar_file = request.files.get("avatar")
    if avatar_file:
        rel_path = save_mentor_avatar(avatar_file, mentor.id)
        if rel_path:
            if hasattr(mentor, "avatar_path"):
                mentor.avatar_path = rel_path
            elif hasattr(mentor, "avatar"):
                mentor.avatar = rel_path

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "خطای یکتا بودن داده‌ها (مثل ایمیل تکراری)."}), 400

    return jsonify(mentor_to_dict(mentor)), 200


@api_bp.patch("/mentors/<int:mentor_id>")
@api_auth_required()
def api_mentor_partial_update(mentor_id: int):
    """
    PATCH برای soft delete یا بروزرسانی چند فیلد ساده
    """
    data = request.get_json(silent=True) or {}

    mentor = Mentor.query.get_or_404(mentor_id)

    if "is_deleted" in data and hasattr(Mentor, "is_deleted"):
        mentor.is_deleted = bool(data.get("is_deleted"))

    if "status" in data and hasattr(Mentor, "status"):
        mentor.status = data.get("status") or None

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "بروزرسانی منتور با خطا مواجه شد."}), 400

    return jsonify(mentor_to_dict(mentor)), 200


# ======================================================
# Courses API
# ======================================================

def _to_int_or_none(value):
    try:
        return int(value)
    except Exception:
        return None


def _to_float_or_none(value):
    try:
        return float(value)
    except Exception:
        return None


@api_bp.route("/courses", methods=["GET"])
@api_auth_required()
def api_courses_index():
    """
    لیست دوره‌ها برای Nuxt
    """
    q = request.args.get("q", type=str, default="") or ""
    status = request.args.get("status", type=str, default="") or ""

    page = request.args.get("page", type=int, default=1)
    per_page = request.args.get("per_page", type=int, default=20)

    query = Course.query

    if hasattr(Course, "is_deleted"):
        query = query.filter(Course.is_deleted.is_(False))

    if q:
        like = f"%{q.strip()}%"
        conds = []
        if isinstance(getattr(Course, "title", None), InstrumentedAttribute):
            conds.append(Course.title.ilike(like))
        if isinstance(getattr(Course, "mentor_name", None), InstrumentedAttribute):
            conds.append(Course.mentor_name.ilike(like))
        if conds:
            query = query.filter(or_(*conds))

    if status:
        query = query.filter(Course.status == status.upper())

    query = query.order_by(Course.id.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = [course_to_dict(c) for c in pagination.items]

    return jsonify({
        "items": items,
        "total": pagination.total,
        "page": page,
        "per_page": per_page,
    })


@api_bp.route("/courses/<int:course_id>", methods=["GET"])
@api_auth_required()
def api_course_detail(course_id):
    """
    جزئیات یک دوره برای پروفایل.
    """
    course = Course.query.get_or_404(course_id)

    if getattr(course, "is_deleted", False):
        return jsonify({"error": "not_found"}), 404

    payload = {
        "course": course_to_dict(course),
        "sessions": [],
        "students": [],
        "finance": None,
    }
    return jsonify(payload)


@api_bp.route("/courses", methods=["POST"])
@api_auth_required()
def api_course_create():
    from flask import request, jsonify

    form = request.form
    files = request.files

    title = (form.get("title") or "").strip()
    if not title:
        return jsonify({"error": "نام دوره الزامی است."}), 400

    # 🔹 فقط فیلدهایی را پاس می‌دهیم که واقعاً در مدل Course وجود دارند
    kwargs = {}

    # ستونی که مطمئناً داری
    kwargs["title"] = title

    if hasattr(Course, "mentor_id"):
        kwargs["mentor_id"] = _to_int_or_none(form.get("mentor_id"))

    if hasattr(Course, "status"):
        kwargs["status"] = (form.get("status") or "ACTIVE").upper()

    if hasattr(Course, "description"):
        kwargs["description"] = form.get("description") or None

    # 🔸 تاریخ‌ها → تبدیل به date
    if hasattr(Course, "start_date"):
        kwargs["start_date"] = _parse_date_field(form.get("start_date"))

    if hasattr(Course, "end_date"):
        kwargs["end_date"] = _parse_date_field(form.get("end_date"))

    # اگر در مدل ستون start_time / end_time وجود ندارد، اصلاً اضافه‌شان نمی‌کنیم
    if hasattr(Course, "start_time"):
        kwargs["start_time"] = form.get("start_time") or None
    if hasattr(Course, "end_time"):
        kwargs["end_time"] = form.get("end_time") or None

    # مالی
    if hasattr(Course, "fee_per_student"):
        kwargs["fee_per_student"] = _to_float_or_none(form.get("fee_per_student"))

    if hasattr(Course, "mentor_share_percent"):
        kwargs["mentor_share_percent"] = _to_float_or_none(form.get("mentor_share_percent"))

    # capacity / category / level اگر وجود دارد
    if hasattr(Course, "capacity"):
        kwargs["capacity"] = _to_int_or_none(form.get("capacity"))

    if hasattr(Course, "category"):
        kwargs["category"] = form.get("category") or None

    if hasattr(Course, "level"):
        kwargs["level"] = form.get("level") or None

    # اگر بعداً schedule_type و ... را به مدل اضافه کردی، این‌ها فعال می‌شوند
    if hasattr(Course, "schedule_type"):
        kwargs["schedule_type"] = form.get("schedule_type") or None
    if hasattr(Course, "schedule_days"):
        kwargs["schedule_days"] = form.get("schedule_days") or None
    if hasattr(Course, "schedule_pattern"):
        kwargs["schedule_pattern"] = form.get("schedule_pattern") or None
    if hasattr(Course, "weekly_days_json"):
        kwargs["weekly_days_json"] = form.get("weekly_days_json") or None
    if hasattr(Course, "sessions_json"):
        kwargs["sessions_json"] = form.get("sessions_json") or None

    # ✅ ساخت شیء Course فقط با فیلدهای معتبر
    course = Course(**kwargs)

    db.session.add(course)
    db.session.commit()  # برای اینکه course.id داشته باشیم

    # ذخیره‌ی کاور اگر ارسال شده
    file_storage = files.get("cover_image")
    if file_storage:
        rel = save_course_cover(file_storage, course.id)
        if rel:
            if hasattr(course, "cover_image"):
                course.cover_image = rel
            elif hasattr(course, "cover_path"):
                course.cover_path = rel
            db.session.commit()

    return jsonify(course_to_dict(course)), 201


@api_bp.route("/courses/<int:course_id>", methods=["PUT"])
@api_auth_required()
def api_course_update(course_id):
    from flask import request, jsonify

    course = Course.query.get_or_404(course_id)

    # soft-delete check
    if getattr(course, "is_deleted", False):
        return jsonify({"error": "not_found"}), 404

    form = request.form
    files = request.files

    # عنوان
    if "title" in form:
        title = (form.get("title") or "").strip()
        if title:
            course.title = title

    # منتور
    if "mentor_id" in form and hasattr(Course, "mentor_id"):
        course.mentor_id = _to_int_or_none(form.get("mentor_id"))

    # وضعیت
    if "status" in form and hasattr(Course, "status"):
        status = (form.get("status") or "").strip()
        if status:
            course.status = status.upper()

    # 🔸 تاریخ‌ها (با تبدیل به date)
    if hasattr(Course, "start_date") and "start_date" in form:
        raw = (form.get("start_date") or "").strip()
        course.start_date = _parse_date_field(raw) if raw else None

    if hasattr(Course, "end_date") and "end_date" in form:
        raw = (form.get("end_date") or "").strip()
        course.end_date = _parse_date_field(raw) if raw else None

    # ساعت‌ها (فقط اگر ستونش در مدل باشد)
    if hasattr(Course, "start_time") and "start_time" in form:
        course.start_time = form.get("start_time") or None

    if hasattr(Course, "end_time") and "end_time" in form:
        course.end_time = form.get("end_time") or None

    # توضیحات
    if hasattr(Course, "description") and "description" in form:
        course.description = form.get("description") or None

    # مالی
    if hasattr(Course, "fee_per_student") and "fee_per_student" in form:
        course.fee_per_student = _to_float_or_none(form.get("fee_per_student"))

    if hasattr(Course, "mentor_share_percent") and "mentor_share_percent" in form:
        course.mentor_share_percent = _to_float_or_none(form.get("mentor_share_percent"))

    # capacity / category / level
    if hasattr(Course, "capacity") and "capacity" in form:
        course.capacity = _to_int_or_none(form.get("capacity"))

    if hasattr(Course, "category") and "category" in form:
        course.category = form.get("category") or None

    if hasattr(Course, "level") and "level" in form:
        course.level = form.get("level") or None

    # schedule_* اگر در مدل باشد
    if hasattr(Course, "schedule_type") and "schedule_type" in form:
        course.schedule_type = form.get("schedule_type") or None

    if hasattr(Course, "schedule_days") and "schedule_days" in form:
        course.schedule_days = form.get("schedule_days") or None

    if hasattr(Course, "schedule_pattern") and "schedule_pattern" in form:
        course.schedule_pattern = form.get("schedule_pattern") or None

    if hasattr(Course, "weekly_days_json") and "weekly_days_json" in form:
        course.weekly_days_json = form.get("weekly_days_json") or None

    if hasattr(Course, "sessions_json") and "sessions_json" in form:
        course.sessions_json = form.get("sessions_json") or None

    # کاور جدید
    file_storage = files.get("cover_image")
    if file_storage:
        # اول قبلی را حذف کن (اگر فانکشن delete_course_cover داری)
        try:
            delete_course_cover(course)
        except Exception:
            pass

        rel = save_course_cover(file_storage, course.id)
        if rel:
            if hasattr(course, "cover_image"):
                course.cover_image = rel
            elif hasattr(course, "cover_path"):
                course.cover_path = rel

    db.session.commit()
    return jsonify(course_to_dict(course)), 200


@api_bp.route("/courses/<int:course_id>", methods=["PATCH"])
@api_auth_required()
def api_course_partial_update(course_id):
    course = Course.query.get_or_404(course_id)

    if getattr(course, "is_deleted", False):
        return jsonify({"error": "not_found"}), 404

    data = request.get_json(silent=True) or {}

    status = data.get("status")
    if status:
        course.status = status.upper()

    db.session.commit()
    return jsonify(course_to_dict(course))
# =========================
#   Finance – Mentors
# =========================

@api_bp.get("/finance/mentors/summary")
@api_auth_required()
def api_finance_mentors_summary():
    """
    خلاصه مالی منتورها برای داشبورد/لیست در فرانت Nuxt.

    خروجی:
      {
        "items": [
          {
            "mentor_id": 1,
            "mentor_name": "...",
            "email": "...",
            "courses_count": 0,
            "received": 0,
            "share": 0,
            "paid": 0,
            "due": 0
          },
          ...
        ],
        "total": <تعداد منتور>
      }
    """
    # این جمع فعلاً فقط بر اساس MentorPayment است.
    # منطق دقیق‌تر سهم منتور از شهریه دوره‌ها را اگر خواستی بعداً
    # بر اساس مدل‌های enrollment/finance می‌توانیم هوشمندتر کنیم.
    rows = (
        db.session.query(
            Mentor.id.label("mentor_id"),
            Mentor.first_name,
            Mentor.last_name,
            Mentor.email,
            func.coalesce(
                func.sum(
                    case((MentorPayment.kind == "INCOME", MentorPayment.amount), else_=0)
                ),
                0,
            ).label("income"),
            func.coalesce(
                func.sum(
                    case((MentorPayment.kind == "EXPENSE", MentorPayment.amount), else_=0)
                ),
                0,
            ).label("expense"),
        )
        .outerjoin(MentorPayment, MentorPayment.mentor_id == Mentor.id)
        .group_by(Mentor.id, Mentor.first_name, Mentor.last_name, Mentor.email)
        .order_by(Mentor.id.desc())
        .all()
    )

    items = []
    for r in rows:
        income = int(r.income or 0)
        expense = int(r.expense or 0)
        balance = income - expense

        full_name = (r.first_name or "") + " " + (r.last_name or "")
        full_name = full_name.strip() or None

        items.append(
            {
                "mentor_id": r.mentor_id,
                "mentor_name": full_name,
                "email": r.email,
                # فعلاً تعداد دوره 0؛ اگر مدل مربوط به دوره‌ها را وصل کنیم این را هم پر می‌کنیم
                "courses_count": 0,
                # فرض ساده:
                # received = مجموع INCOME
                # share    = فعلاً همان received
                # paid     = مجموع EXPENSE
                # due      = share - paid
                "received": income,
                "share": income,
                "paid": expense,
                "due": balance,
            }
        )

    return jsonify({"items": items, "total": len(items)})
@api_bp.get("/finance/mentors/<int:mentor_id>/payments")
@api_auth_required()
def api_finance_mentor_payments(mentor_id: int):
    """
    لیست تراکنش‌های مالی یک منتور.
    GET /api/finance/mentors/<id>/payments
    """
    mentor = Mentor.query.get_or_404(mentor_id)

    q = (
        MentorPayment.query.filter_by(mentor_id=mentor.id)
        .order_by(MentorPayment.paid_at.desc())
        .all()
    )

    items = [mentor_payment_to_dict(p) for p in q]
    income = sum(p.amount for p in q if p.kind == "INCOME")
    expense = sum(p.amount for p in q if p.kind == "EXPENSE")

    return jsonify(
        {
            "mentor": mentor_to_dict(mentor),
            "items": items,
            "totals": {
                "income": int(income or 0),
                "expense": int(expense or 0),
                "balance": int((income or 0) - (expense or 0)),
            },
        }
    ), 200


@api_bp.post("/finance/mentors/<int:mentor_id>/payments")
@api_auth_required()
def api_finance_mentor_payment_create(mentor_id: int):
    """
    ثبت تراکنش جدید برای منتور

    POST /api/finance/mentors/<id>/payments
    Body (JSON):
      {
        "amount": 2500000,       # الزامی، تومان
        "kind": "EXPENSE",       # 'INCOME' یا 'EXPENSE' (پیش‌فرض EXPENSE)
        "title": "تسویه قسط اول",
        "note": "...",
        "paid_at": "2025-01-10T12:30:00"   # اختیاری، ISO 8601
      }
    """
    mentor = Mentor.query.get_or_404(mentor_id)

    payload = request.get_json(silent=True) or {}
    try:
        amount = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0

    if amount <= 0:
        return jsonify({"error": "مبلغ معتبر نیست."}), 400

    kind = (payload.get("kind") or "EXPENSE").upper()
    if kind not in ("INCOME", "EXPENSE"):
        return jsonify({"error": "نوع تراکنش نامعتبر است (فقط INCOME یا EXPENSE)."}), 400

    title = (payload.get("title") or "").strip() or None
    note = (payload.get("note") or "").strip() or None

    paid_at_raw = payload.get("paid_at")
    if paid_at_raw:
        try:
            # رشته ISO 8601
            paid_at = datetime.fromisoformat(paid_at_raw)
        except Exception:
            paid_at = datetime.utcnow()
    else:
        paid_at = datetime.utcnow()

    p = MentorPayment(
        mentor_id=mentor.id,
        amount=amount,
        kind=kind,
        title=title,
        note=note,
        paid_at=paid_at,
    )

    db.session.add(p)
    db.session.commit()

    return jsonify(mentor_payment_to_dict(p)), 201
@api_bp.patch("/finance/payments/<int:payment_id>")
@api_auth_required()
def api_finance_payment_update(payment_id: int):
    """
    ویرایش ساده یک تراکنش MentorPayment (بدون حذف).

    Body (JSON – همه فیلدها اختیاری‌اند):
      {
        "amount": 3000000,
        "kind": "EXPENSE",
        "title": "...",
        "note": "...",
        "paid_at": "2025-01-10T12:30:00"
      }
    """
    p = MentorPayment.query.get_or_404(payment_id)

    payload = request.get_json(silent=True) or {}

    if "amount" in payload:
        try:
            amt = int(payload.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0
        if amt > 0:
            p.amount = amt

    if "kind" in payload:
        kind = (payload.get("kind") or "").upper()
        if kind in ("INCOME", "EXPENSE"):
            p.kind = kind

    if "title" in payload:
        p.title = (payload.get("title") or "").strip() or None
    if "note" in payload:
        p.note = (payload.get("note") or "").strip() or None

    if "paid_at" in payload and payload.get("paid_at"):
        try:
            p.paid_at = datetime.fromisoformat(payload.get("paid_at"))
        except Exception:
            pass

    db.session.commit()
    return jsonify(mentor_payment_to_dict(p)), 200
# =========================
#   Course Sessions API
# =========================

def _safe_date_to_str(dt):
    """کمک برای تبدیل تاریخ/دیتایم به رشته قابل JSON."""
    if not dt:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


@api_bp.get("/courses/<int:course_id>/sessions")
@api_auth_required()
def api_course_sessions(course_id: int):
    """
    لیست جلسات یک دوره + آمار حضور/غیاب هر جلسه
    GET /api/courses/<course_id>/sessions
    خروجی:
      {
        "items": [...],
        "total": 5
      }
    """
    # همه جلسات این دوره
    sessions = (
        CourseSession.query
        .filter_by(course_id=course_id)
        .order_by(
            getattr(CourseSession, "session_date", getattr(CourseSession, "date"))
        )
        .all()
    )

    session_ids = [getattr(s, "id", None) for s in sessions if getattr(s, "id", None)]
    stats_map: dict[int, dict] = {}

    if session_ids:
        q = (
            db.session.query(
                Attendance.session_id.label("sid"),
                func.count(Attendance.id).label("total"),
                func.sum(
                    case((Attendance.status == "PRESENT", 1), else_=0)
                ).label("present"),
                func.sum(
                    case((Attendance.status == "ABSENT", 1), else_=0)
                ).label("absent"),
            )
            .filter(Attendance.session_id.in_(session_ids))
            .group_by(Attendance.session_id)
        )

        for row in q:
            stats_map[row.sid] = {
                "total": int(row.total or 0),
                "present": int(row.present or 0),
                "absent": int(row.absent or 0),
            }

    items = []
    for s in sessions:
        sid = getattr(s, "id", None)
        items.append(session_to_dict(s, stats_map.get(sid, {})))

    return jsonify({"items": items, "total": len(items)}), 200

# ---------- Finance Dashboard (API for Nuxt) ----------

@api_bp.get("/finance/dashboard")
@api_auth_required()
def api_finance_dashboard():
    """
    داشبورد مالی برای Nuxt.
    فعلاً نسخه‌ی ساده (stub) که فقط ساختار می‌دهد؛ بعداً آمار واقعی وصل می‌کنیم.

    GET /api/finance/dashboard
    """
    kpis = {
        "total_face": 0,          # شهریه اسمی کل
        "total_received": 0,      # مجموع دریافتی
        "total_receivables": 0,   # مطالبات باز (face - received)
        "overdue_count": 0,       # تعداد اقساط سررسید گذشته
        "aging": {                # A/R Aging
            "0-30": 0,
            "31-60": 0,
            "61-90": 0,
            "90+": 0,
        },
        "mtd_expense": 0,         # هزینه ماه جاری
        "total_expense": 0,       # مجموع کل هزینه‌ها
    }

    payload = {
        "kpis": kpis,

        # درآمد ماهانه (برای چارت بالا)
        # انتظار front: هر آیتم چیزی شبیه {"ym": "2025-11", "amount": 123456}
        "monthly": [],

        # مطالبات دانشجو (تب "مطالبات")
        "receivables": [],

        # صورت‌حساب دوره‌ها (تب "دوره‌ها")
        "courses": [],

        # تسویه منتورها (تب "منتورها")
        "mentors": [],

        # اقساط (تب "اقساط")
        "installments": [],

        # دارایی‌ها (تب "دارایی‌ها")
        "assets": [],

        # هزینه‌ها (تب "هزینه‌ها")
        "expenses": [],
    }

    return jsonify(payload), 200
# ---------- دانشجوهای یک دوره ----------

def _enrollment_to_dict(en, st: Student | None = None) -> dict:
    """خروجی استاندارد دانشجوی ثبت‌نام‌شده در دوره."""
    st = st or getattr(en, "student", None)

    full_name = None
    if st is not None:
        full_name = getattr(st, "full_name", None)
        if not full_name:
            first = getattr(st, "first_name", "") or ""
            last = getattr(st, "last_name", "") or ""
            full_name = f"{first} {last}".strip() or None

    phone = getattr(st, "phone", None) if st is not None else None

    status = getattr(en, "status", None) or "REGISTERED"

    return {
        "id": getattr(en, "id", None),
        "enrollment_id": getattr(en, "id", None),
        "student_id": getattr(en, "student_id", None),
        "full_name": full_name,
        "student_name": full_name,
        "phone": phone,
        "student_phone": phone,
        "status": status,
    }

@api_bp.route("/courses/<int:course_id>/students", methods=["GET"])
@api_auth_required()
def api_course_students(course_id):
    """لیست دانشجوهای ثبت‌نام‌شده + دانشجوهای قابل انتخاب (حذف‌نشده و هنوز در این دوره نیستند)"""
    from flask import jsonify

    course = Course.query.get_or_404(course_id)

    # دانشجوهای ثبت‌نام شده در این دوره
    enrolled_q = (
        db.session.query(Student)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .filter(
            Enrollment.course_id == course.id,
            getattr(Student, "is_deleted", False) == False,  # noqa: E712
        )
        .order_by(Student.id.desc())
    )
    enrolled = [_student_brief(st) for st in enrolled_q]

    # id های ثبت‌نام شده
    enrolled_ids = [s["id"] for s in enrolled]

    # دانشجوهای قابل انتخاب (is_deleted = False و هنوز تو این دوره نیستند)
    available_q = Student.query.filter(
        getattr(Student, "is_deleted", False) == False,  # noqa: E712
        ~Student.id.in_(enrolled_ids) if enrolled_ids else True,
    ).order_by(Student.id.desc())
    available = [_student_brief(st) for st in available_q]

    return jsonify({
        "course_id": course.id,
        "enrolled": enrolled,
        "available": available,
        "counts": {
            "enrolled": len(enrolled),
            "available": len(available),
        },
    }), 200
# ---------- خلاصه مالی دوره ----------

@api_bp.get("/courses/<int:course_id>/finance")
@api_auth_required()
def api_course_finance(course_id: int):
    """
    خلاصه مالی دوره برای تب Financial پروفایل دوره.
    اگر الان هنوز مدل مالی/پرداخت‌ها را وصل نکردی، حداقل
    face / received / remain را بر اساس fee_per_student * تعداد دانشجو برمی‌گردانیم.
    """
    from app.models.course import Course

    course = Course.query.get_or_404(course_id)

    # تعداد دانشجو بر اساس Enrollment اگر وجود داشته باشد
    students_count = 0
    if Enrollment is not None:
        students_count = (
            db.session.query(func.count(Enrollment.id))
            .filter(Enrollment.course_id == course_id)
            .scalar()
            or 0
        )

    fee_per_student = getattr(course, "fee_per_student", None) or 0
    total_face = int(fee_per_student * students_count)

    # اگر بعداً مدل Payment / InstallmentPlan داری، این سه تا رو دقیق حساب کن.
    total_received = 0
    total_receivables = total_face - total_received

    mentor_share_percent = getattr(course, "mentor_share_percent", None) or 0
    mentor_share_amount = int(total_face * mentor_share_percent / 100.0)
    mentor_paid = 0
    mentor_due = mentor_share_amount - mentor_paid

    return jsonify(
        {
            "face": total_face,
            "total_face": total_face,
            "received": total_received,
            "total_received": total_received,
            "remain": total_receivables,
            "total_receivables": total_receivables,
            "students_count": students_count,
            "fee_per_student": fee_per_student,
            "mentor_share_percent": mentor_share_percent,
            "mentor_share": mentor_share_amount,
            "mentor_paid": mentor_paid,
            "mentor_due": mentor_due,
        }
    ), 200


@api_bp.route("/courses/<int:course_id>/students/enroll", methods=["POST"])
@api_auth_required()
def api_course_students_enroll(course_id):
    """ثبت‌نام یک دانشجو در دوره (enroll)"""
    from flask import request, jsonify

    course = Course.query.get_or_404(course_id)

    # هم JSON و هم فرم را پشتیبانی کنیم
    data = request.get_json(silent=True) or request.form or {}
    sid = data.get("student_id")
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        sid = None

    if not sid:
        return jsonify({"ok": False, "error": "student_id لازم است"}), 400

    student = Student.query.get_or_404(sid)
    if getattr(student, "is_deleted", False):
        return jsonify({"ok": False, "error": "student حذف شده است"}), 400

    # اگر قبلاً ثبت‌نام شده، دوباره چیزی نساز
    exists = Enrollment.query.filter_by(course_id=course.id, student_id=student.id).first()
    if exists:
        return jsonify({"ok": True, "message": "قبلاً ثبت‌نام شده"}), 200

    enr = Enrollment(course_id=course.id, student_id=student.id)
    db.session.add(enr)
    db.session.commit()

    return jsonify({"ok": True}), 201


@api_bp.route("/courses/<int:course_id>/students/unenroll", methods=["POST"])
@api_auth_required()
def api_course_students_unenroll(course_id):
    """خارج کردن یک دانشجو از دوره (حذف ثبت‌نام)"""
    from flask import request, jsonify

    course = Course.query.get_or_404(course_id)

    data = request.get_json(silent=True) or request.form or {}
    sid = data.get("student_id")
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        sid = None

    if not sid:
        return jsonify({"ok": False, "error": "student_id لازم است"}), 400

    enr = Enrollment.query.filter_by(course_id=course.id, student_id=sid).first()
    if not enr:
        return jsonify({"ok": True, "message": "قبلاً حذف شده / یافت نشد"}), 200

    db.session.delete(enr)
    db.session.commit()
    return jsonify({"ok": True}), 200
def _student_to_dict(st: Student):
    name = ((st.first_name or '') + ' ' + (st.last_name or '')).strip()
    if not name and hasattr(st, "full_name"):
        name = (st.full_name or "").strip()
    return {
        "id": st.id,
        "name": name or "—",
        "email": st.email or "",
        "phone": st.phone or "",
    }

# 🔹 لیست دانشجوهای ثبت‌نام‌شده در یک دوره
@api_bp.get("/courses/<int:course_id>/enrollments")
@api_auth_required()
def api_course_enrollments_list(course_id):
    Course.query.get_or_404(course_id)

    rows = (
        db.session.query(Enrollment, Student)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(Enrollment.course_id == course_id)
        .order_by(Student.last_name.asc(), Student.first_name.asc(), Student.id.asc())
        .all()
    )

    items = []
    for e, st in rows:
        items.append({
            "id": e.id,                  # id ثبت‌نام (Enrollment)
            "student_id": st.id,
            "student": _student_to_dict(st),
            "status": getattr(e, "status", "ACTIVE") or "ACTIVE",
        })

    return jsonify({"items": items, "total": len(items)}), 200


# 🔹 لیست دانشجوهایی که می‌توانند در این دوره ثبت‌نام شوند
@api_bp.get("/courses/<int:course_id>/students/available")
@api_auth_required()
def api_course_students_available(course_id):
    Course.query.get_or_404(course_id)

    q = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", type=int) or 50
    limit = max(1, min(limit, 100))

    enrolled_ids_subq = (
        db.session.query(Enrollment.student_id)
        .filter(Enrollment.course_id == course_id)
        .subquery()
    )

    qry = Student.query.filter(~Student.id.in_(enrolled_ids_subq))

    # فقط دانشجوهایی که is_deleted آنها False است (اگر ستون وجود داشته باشد)
    if hasattr(Student, "is_deleted"):
        qry = qry.filter(
            or_(Student.is_deleted.is_(False), Student.is_deleted.is_(None))
        )

    if q:
        like = f"%{q}%"
        id_filter = (Student.id == int(q)) if q.isdigit() else False
        qry = qry.filter(
            or_(
                id_filter,
                Student.first_name.ilike(like),
                Student.last_name.ilike(like),
                Student.email.ilike(like),
                Student.phone.ilike(like),
            )
        )

    students = (
        qry.order_by(Student.last_name.asc(), Student.first_name.asc())
        .limit(limit)
        .all()
    )

    return jsonify({
        "items": [_student_to_dict(s) for s in students],
        "total": len(students),
    }), 200


# 🔹 افزودن یک دانشجو به دوره
@api_bp.post("/courses/<int:course_id>/enrollments")
@api_auth_required()
def api_course_enrollment_add(course_id):
    Course.query.get_or_404(course_id)

    payload = request.get_json(silent=True) or {}
    student_id = payload.get("student_id")

    try:
        student_id = int(student_id)
    except Exception:
        student_id = None

    if not student_id:
        return jsonify({"error": "student_id لازم است"}), 400

    student = Student.query.get_or_404(student_id)

    if hasattr(Student, "is_deleted") and student.is_deleted:
        return jsonify({"error": "این دانشجو غیرفعال است"}), 400

    exists = (
        Enrollment.query
        .filter_by(course_id=course_id, student_id=student_id)
        .first()
    )
    if exists:
        # از نظر فرانت مهم این است که اوکی است؛ فقط پیام بده که قبلاً بوده
        return jsonify({"ok": True, "message": "قبلاً ثبت شده"}), 200

    now_utc = datetime.utcnow()
    e = Enrollment(course_id=course_id, student_id=student_id, status="ACTIVE")
    if hasattr(Enrollment, "enrolled_at"):
        e.enrolled_at = now_utc
    if hasattr(Enrollment, "joined_at"):
        e.joined_at = now_utc

    db.session.add(e)
    db.session.commit()

    return jsonify({"ok": True, "id": e.id}), 201


# 🔹 حذف ثبت‌نام یک دانشجو از دوره
@api_bp.delete("/courses/<int:course_id>/enrollments/<int:enrollment_id>")
@api_auth_required()
def api_course_enrollment_delete(course_id, enrollment_id):
    Course.query.get_or_404(course_id)

    e = (
        Enrollment.query
        .filter_by(id=enrollment_id, course_id=course_id)
        .first_or_404()
    )

    db.session.delete(e)
    db.session.commit()
    return jsonify({"ok": True}), 200
# -----------------------------
# Helpers
# -----------------------------
def _api_student_dict(s: Student):
    full = f"{(s.first_name or '').strip()} {(s.last_name or '').strip()}".strip()
    if not full and hasattr(s, "full_name"):
        full = (s.full_name or "").strip()
    return {
        "id": s.id,
        "name": full or f"دانشجو #{s.id}",
        "email": s.email or "",
        "phone": s.phone or "",
    }


# -----------------------------
# ۲) افزودن دانشجو به دوره
# -----------------------------
@api_bp.post("/courses/<int:course_id>/students", endpoint="api_course_students_add")
@api_auth_required()
def api_course_students_add(course_id: int):
    course = Course.query.get_or_404(course_id)

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        student_id = payload.get("student_id")
    else:
        student_id = request.form.get("student_id")

    try:
        student_id = int(student_id)
    except Exception:
        student_id = None

    if not student_id:
        return jsonify({"ok": False, "error": "student_id لازم است"}), 400

    exists = Enrollment.query.filter_by(course_id=course.id, student_id=student_id).first()
    if exists:
        return jsonify({"ok": False, "error": "قبلاً ثبت شده"}), 409

    now_utc = datetime.utcnow()
    e = Enrollment(course_id=course.id, student_id=student_id, status="ACTIVE")
    if hasattr(Enrollment, "enrolled_at"):
        setattr(e, "enrolled_at", now_utc)
    if hasattr(Enrollment, "joined_at"):
        setattr(e, "joined_at", now_utc)

    db.session.add(e)
    db.session.commit()
    return jsonify({"ok": True, "id": e.id})
# -----------------------------
# ۳) حذف دانشجو از دوره
# -----------------------------
@api_bp.delete("/courses/<int:course_id>/students/<int:student_id>", endpoint="api_course_students_remove")
@api_auth_required()
def api_course_students_remove(course_id: int, student_id: int):
    course = Course.query.get_or_404(course_id)

    enr = Enrollment.query.filter_by(course_id=course.id, student_id=student_id).first()
    if not enr:
        return jsonify({"ok": True, "message": "قبلاً حذف شده/یافت نشد"}), 200

    db.session.delete(enr)
    db.session.commit()
    return jsonify({"ok": True})
@api_bp.route("/courses/<int:course_id>/sessions/generate", methods=["POST"])
@api_auth_required()
def api_course_sessions_generate(course_id):
    """
    تولید خودکار جلسات دوره براساس برنامه‌ی زمانی (هم‌منطق با /courses/.../sessions/generate).
    خروجی: {ok: True, created: n} یا error.
    """
    from flask import request, jsonify
    import json

    course = Course.query.get_or_404(course_id)

    # اگر soft-delete داری
    if getattr(course, "is_deleted", False):
        return jsonify({"error": "not_found"}), 404

    # همون ولیدیشن موجود در courses/routes.py
    ok, err = _validate_schedule_inputs_for(course)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    # اگر قبلاً جلسه ساخته شده، مثل نسخه‌ی HTML کد 409 بده
    existing = CourseSession.query.filter_by(course_id=course_id).count()
    if existing:
        return jsonify({"ok": False, "error": "جلسات قبلاً ساخته شده"}), 409

    # بدنه‌ی درخواست: exclude, sessions_json و ...
    body = request.get_json(silent=True) or {}
    if not body and request.form:
        try:
            body = json.loads(request.form.get("payload") or "{}")
        except Exception:
            body = {}

    exclude = _norm_dates_str_list(body.get("exclude") or [])

    st = (getattr(course, "schedule_type", "DATES") or "DATES").upper()
    final_days = set()

    # حالت هفتگی (weekly) – از همون helper استفاده می‌کنیم
    if st == "WEEKLY":
        final_days = _generate_dates_weekly(course, exclude)
    else:
        # حالت CUSTOM/DATES: یا از body.sessions_json، یا از خود course.sessions_json
        raw_dates = body.get("sessions_json") or getattr(course, "sessions_json", []) or []
        cand = _norm_dates_str_list(raw_dates)
        for d in cand:
            if course.start_date <= d <= course.end_date and d not in exclude:
                final_days.add(d)

    if not final_days:
        return jsonify({"ok": False, "error": "هیچ تاریخی برای ایجاد جلسه یافت نشد."}), 400

    print("تاریخ‌های ایجاد شده برای جلسات (API):")
    for d in sorted(final_days):
        print(f"- {d}")

    # ذخیره جلسات – دقیقاً هم‌رفتار با courses/routes.py
    for d in sorted(final_days):
        # d از نوع datetime.date است
        session_dt = datetime.combine(d, datetime.min.time())
        db.session.add(CourseSession(course_id=course_id, date=session_dt, session_date=d))

    db.session.commit()
    return jsonify({"ok": True, "created": len(final_days)}), 201
# -----------------------------
# Session detail + files (API)
# -----------------------------
def _session_file_to_dict(f):
    return {
        "id": f.id,
        "file_path": f.file_path,
        "description": f.description or "",
        "uploaded_at": f.uploaded_at.isoformat() if getattr(f, "uploaded_at", None) else None,
    }



@api_bp.route("/courses/<int:course_id>/sessions/<int:session_id>", methods=["GET"])
@api_auth_required()
def api_course_session_detail(course_id: int, session_id: int):
    """جزئیات جلسه در کانتکست دوره (برای امنیت و routeهای قدیمی)."""
    s = CourseSession.query.filter_by(id=session_id, course_id=course_id).first_or_404()
    data = session_to_dict(s)

    files = []
    if SessionFile is not None:
        files = [_session_file_to_dict(f) for f in SessionFile.query.filter_by(session_id=s.id).all()]

    return jsonify({"session": data, "files": files})


@api_bp.route("/sessions/<int:session_id>/upload", methods=["POST"])
@api_auth_required()
def api_session_upload_file(session_id: int):
    """آپلود فایل برای یک جلسه. ورودی multipart با کلید 'file'."""
    if SessionFile is None:
        return jsonify({"ok": False, "error": "SessionFile model not found"}), 500

    s = CourseSession.query.get_or_404(session_id)

    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "فایل ارسال نشده است"}), 400

    desc = (request.form.get("description") or "").strip() or None

    rel = save_uploaded_file(file, subdir=f"sessions/{s.id}")
    if not rel:
        return jsonify({"ok": False, "error": "فایل معتبر نیست"}), 400

    rec = SessionFile(session_id=s.id, file_path=rel, description=desc)
    db.session.add(rec)
    db.session.commit()

    return jsonify({"ok": True, "file": _session_file_to_dict(rec)}), 201


@api_bp.route("/courses/<int:course_id>/sessions/<int:session_id>/upload", methods=["POST"])
@api_auth_required()
def api_course_session_upload_file(course_id: int, session_id: int):
    """همان آپلود، ولی زیر URL دوره."""
    if SessionFile is None:
        return jsonify({"ok": False, "error": "SessionFile model not found"}), 500

    s = CourseSession.query.filter_by(id=session_id, course_id=course_id).first_or_404()

    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "فایل ارسال نشده است"}), 400

    desc = (request.form.get("description") or "").strip() or None

    rel = save_uploaded_file(file, subdir=f"sessions/{s.id}")
    if not rel:
        return jsonify({"ok": False, "error": "فایل معتبر نیست"}), 400

    rec = SessionFile(session_id=s.id, file_path=rel, description=desc)
    db.session.add(rec)
    db.session.commit()

    return jsonify({"ok": True, "file": _session_file_to_dict(rec)}), 201


@api_bp.route("/sessions/file/<int:file_id>", methods=["DELETE"])
@api_auth_required()
def api_session_delete_file(file_id: int):
    """حذف فایل یک جلسه (سازگار با فرانت)."""
    if SessionFile is None:
        return jsonify({"ok": False, "error": "SessionFile model not found"}), 500

    f = SessionFile.query.get_or_404(file_id)
    try:
        # فایل روی دیسک هم حذف شود
        from app.utils.media import remove_media
        remove_media(f.file_path)
    except Exception:
        pass

    db.session.delete(f)
    db.session.commit()
    return jsonify({"ok": True})
@api_bp.route("/sessions/<int:session_id>", methods=["PATCH"])
@api_auth_required()
def api_session_partial_update(session_id: int):
    """
    ویرایش ساده‌ی یک جلسه (موضوع، توضیحات، وضعیت)
    PATCH /api/sessions/<id>
    Body (JSON):
      {
        "topic": "جلسه معرفی پروژه",
        "description": "مرور کلی سرفصل‌ها و معرفی تیم‌ها",
        "status": "DONE"
      }
    """
    s = CourseSession.query.get_or_404(session_id)
    payload = request.get_json(silent=True) or {}

    # موضوع جلسه
    if "topic" in payload and hasattr(CourseSession, "topic"):
        s.topic = (payload.get("topic") or "").strip() or "جلسه"

    # توضیحات جلسه
    if "description" in payload and hasattr(CourseSession, "description"):
        s.description = (payload.get("description") or "").strip() or None

    # وضعیت (اختیاری)
    if "status" in payload and hasattr(CourseSession, "status"):
        raw = (payload.get("status") or "").strip()
        if raw:
            s.status = raw.upper()

    db.session.commit()
    return jsonify(session_to_dict(s)), 200


@api_bp.route("/courses/<int:course_id>/sessions/<int:session_id>", methods=["PATCH"])
@api_auth_required()
def api_course_session_partial_update(course_id: int, session_id: int):
    """
    همان ویرایش جلسه، ولی در کانتکست دوره (برای امنیت بیشتر).
    PATCH /api/courses/<course_id>/sessions/<session_id>
    """
    s = CourseSession.query.filter_by(id=session_id, course_id=course_id).first_or_404()
    payload = request.get_json(silent=True) or {}

    if "topic" in payload and hasattr(CourseSession, "topic"):
        s.topic = (payload.get("topic") or "").strip() or "جلسه"

    if "description" in payload and hasattr(CourseSession, "description"):
        s.description = (payload.get("description") or "").strip() or None

    if "status" in payload and hasattr(CourseSession, "status"):
        raw = (payload.get("status") or "").strip()
        if raw:
            s.status = raw.upper()

    db.session.commit()
    return jsonify(session_to_dict(s)), 200
@api_bp.route("/sessions/<int:session_id>", methods=["GET", "OPTIONS"])
def api_session_detail(session_id):
    """
    جزئیات یک جلسه + لیست فایل‌های مربوط به آن
    """
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 204

    # پیدا کردن جلسه
    session_obj = CourseSession.query.get_or_404(session_id)

    # چون مدل SessionFile ستونی به نام is_deleted ندارد، فقط بر اساس session_id فیلتر می‌کنیم
    files = (
        SessionFile.query
        .filter_by(session_id=session_obj.id)
        .order_by(SessionFile.id.desc())
        .all()
    )

    return jsonify(
        {
            "session": {
                "id": session_obj.id,
                "course_id": session_obj.course_id,
                "date": session_obj.date.isoformat() if session_obj.date else None,
                "topic": session_obj.topic,
                "description": session_obj.description,
            },
            "files": [
                {
                    "id": f.id,
                    "file_path": f.file_path,
                    "description": f.description,
                    # اگر ستونی مثل created_at داری:
                    "uploaded_at": getattr(f, "created_at", None).isoformat()
                    if getattr(f, "created_at", None)
                    else None,
                }
                for f in files
            ],
        }
    )
@api_bp.route("/courses/<int:course_id>/attendance", methods=["GET", "POST", "OPTIONS"])
def api_course_attendance(course_id):
    """
    GET  /api/courses/<course_id>/attendance?session_id=XX
        -> برگرداندن وضعیت حضور/غیاب برای یک جلسه

    POST /api/courses/<course_id>/attendance
        body JSON:
        {
            "session_id": 20,
            "items": [
                {"student_id": 1, "status": "PRESENT"},
                {"student_id": 2, "status": "ABSENT"},
                ...
            ]
        }
    """

    # ✅ هندل preflight برای CORS
    if request.method == "OPTIONS":
        return "", 204

    # --------- GET: گرفتن لیست حضور/غیاب یک جلسه ----------
    if request.method == "GET":
        try:
            session_id = int(request.args.get("session_id", "0"))
        except ValueError:
            return jsonify({"error": "session_id نامعتبر است"}), 400

        if not session_id:
            return jsonify({"error": "session_id الزامی است"}), 400

        # مطمئن شو جلسه متعلق به همین دوره است
        session_obj = (
            CourseSession.query
            .filter_by(id=session_id, course_id=course_id)
            .first()
        )
        if not session_obj:
            return jsonify({"error": "جلسه پیدا نشد"}), 404

        # خواندن حضور/غیاب‌ها
        rows = (
            Attendance.query
            .filter_by(session_id=session_obj.id)
            .all()
        )

        items = []
        for a in rows:
            items.append({
                "student_id": a.student_id,
                "status": a.status or "ABSENT",
            })

        return jsonify({
            "session_id": session_obj.id,
            "items": items,
        }), 200

    # --------- POST: ذخیره حضور/غیاب یک جلسه ----------
    data = request.get_json(silent=True) or {}

    try:
        session_id = int(data.get("session_id") or 0)
    except ValueError:
        return jsonify({"error": "session_id نامعتبر است"}), 400

    if not session_id:
        return jsonify({"error": "session_id الزامی است"}), 400

    items = data.get("items") or []

    # اعتبارسنجی جلسه
    session_obj = (
        CourseSession.query
        .filter_by(id=session_id, course_id=course_id)
        .first()
    )
    if not session_obj:
        return jsonify({"error": "جلسه پیدا نشد"}), 404

    # اول حضور/غیاب‌های قبلی این جلسه را پاک می‌کنیم
    Attendance.query.filter_by(session_id=session_obj.id).delete(synchronize_session=False)

    # بعد جدیدها را ذخیره می‌کنیم
    saved = 0
    for item in items:
        student_id = item.get("student_id")
        status = (item.get("status") or "ABSENT").upper()

        if not student_id:
            continue

        att = Attendance(
            session_id=session_obj.id,
            student_id=student_id,
            status=status,
        )

        # اگر مدل Attendance ستون course_id داشت، آن را هم ست کن
        if "course_id" in Attendance.__table__.columns:
            att.course_id = course_id

        db.session.add(att)
        saved += 1

    db.session.commit()

    return jsonify({
        "ok": True,
        "session_id": session_obj.id,
        "saved": saved,
    }), 200
def _installment_to_dict_api(inst: Installment) -> dict:
    """خروجی استاندارد یک قسط برای API فرانت."""
    if not inst:
        return {}
    return {
        "id": inst.id,
        "plan_id": getattr(inst, "plan_id", None) or getattr(inst, "installment_plan_id", None),
        "seq": getattr(inst, "seq", None),
        "title": getattr(inst, "title", None),
        "amount_base": int((getattr(inst, "amount_base", 0) or 0)),
        "cheque_fee_amount": int((getattr(inst, "cheque_fee_amount", 0) or 0)),
        "amount_total": int((getattr(inst, "amount_total", 0) or 0)),
        "due_date": inst.due_date.isoformat() if getattr(inst, "due_date", None) else None,
        "status": (getattr(inst, "status", None) or "PENDING").upper(),
        "note": getattr(inst, "note", None),
    }


def _installment_plan_totals_api(plan_id: int) -> dict:
    """جمع کل، پرداخت‌شده و باقی‌مانده‌ی یک پلن اقساط."""
    if not Installment:
        return {"count": 0, "total": 0, "paid": 0, "remain": 0}

    insts = Installment.query.filter(
        (Installment.plan_id == plan_id)
        | (getattr(Installment, "installment_plan_id", None) == plan_id)
    ).all()

    total = sum((i.amount_total or 0) for i in insts)
    paid = sum((i.amount_total or 0) for i in insts if (i.status or "").upper() == "PAID")

    return {
        "count": len(insts),
        "total": int(total),
        "paid": int(paid),
        "remain": int(max(total - paid, 0)),
    }
@api_bp.get("/students/<int:student_id>/installments")
@api_auth_required()
def api_student_installments(student_id: int):
    """
    لیست برنامه‌های اقساط + اقساط یک دانشجو
    GET /api/students/<id>/installments

    خروجی:
    {
      "items": [   # لیست تک‌تک اقساط
        {
          "id": 1,
          "plan_id": 10,
          "seq": 1,
          "title": "قسط ۱",
          "amount_base": 3000000,
          "cheque_fee_amount": 150000,
          "amount_total": 3150000,
          "due_date": "2025-02-01",
          "status": "PENDING",
          "note": null,
          "course_title": "دوره A",
          "plan_title": "پلن اقساط دانشجو فلانی"
        },
        ...
      ],
      "plans": [   # خلاصه پلن‌ها
        {
          "id": 10,
          "title": "پلن اقساط ...",
          "course_id": 3,
          "student_id": 5,
          "enrollment_id": 12,
          "total_amount": 12600000,
          "installments_count": 4,
          "paid": 3150000,
          "remain": 9450000
        }
      ],
      "summary": {
        "sum_total": 12600000,
        "sum_paid": 3150000,
        "sum_remain": 9450000
      }
    }
    """
    # اگر مدل‌ها در پروژه فعلی هنوز وجود ندارند، خروجی خالی بده
    if not InstallmentPlan or not Installment:
        return jsonify({
            "items": [],
            "plans": [],
            "summary": {
                "sum_total": 0,
                "sum_paid": 0,
                "sum_remain": 0,
            },
        })

    # خود دانشجو
    student = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    # ۱) پلن‌هایی که مستقیم به student_id وصل شده‌اند
    direct_plans = (
        InstallmentPlan.query
        .options(db.joinedload(InstallmentPlan.installments))
        .filter(InstallmentPlan.student_id == student.id)
        .all()
    )

    # ۲) پلن‌هایی که از طریق Enrollment وصل شده‌اند
    enrol_ids: list[int] = []
    if Enrollment is not None:
        enrol_ids = [
            e.id for e in Enrollment.query.filter_by(student_id=student.id).all()
            if getattr(e, "id", None)
        ]

    via_enrollment = []
    if enrol_ids:
        via_enrollment = (
            InstallmentPlan.query
            .options(db.joinedload(InstallmentPlan.installments))
            .filter(InstallmentPlan.enrollment_id.in_(enrol_ids))
            .all()
        )

    # ادغام همه پلن‌ها
    plans_map: dict[int, InstallmentPlan] = {}
    for p in direct_plans + via_enrollment:
        if not getattr(p, "id", None):
            continue
        plans_map[p.id] = p

    items: list[dict] = []

    for p in plans_map.values():
        course = getattr(p, "course", None)
        course_title = getattr(course, "title", None) if course is not None else None

        for inst in getattr(p, "installments", []) or []:
            row = _installment_to_dict_api(inst)
            row["course_title"] = course_title
            row["plan_title"] = p.title
            items.append(row)

    # خلاصه هر پلن
    plans_payload: list[dict] = []
    sum_total = 0
    sum_paid = 0

    for p in plans_map.values():
        stats = _installment_plan_totals_api(p.id)
        sum_total += stats["total"]
        sum_paid += stats["paid"]

        plans_payload.append({
            "id": p.id,
            "title": p.title,
            "course_id": getattr(p, "course_id", None),
            "student_id": getattr(p, "student_id", None),
            "enrollment_id": getattr(p, "enrollment_id", None),
            "total_amount": int(getattr(p, "total_amount", 0) or 0),
            "installments_count": getattr(p, "installments_count", None),
            "paid": stats["paid"],
            "remain": stats["remain"],
        })

    summary = {
        "sum_total": int(sum_total),
        "sum_paid": int(sum_paid),
        "sum_remain": int(max(sum_total - sum_paid, 0)),
    }

    return jsonify({
        "items": items,
        "plans": plans_payload,
        "summary": summary,
    })
@api_bp.get("/students/<int:student_id>/courses")
@api_auth_required()
def api_student_courses(student_id):
    """لیست دوره‌هایی که این دانشجو در آن ثبت‌نام شده است"""
    student = Student.query.get_or_404(student_id)

    # جوین Enrollment + Course + Mentor
    rows = (
        db.session.query(Enrollment, Course, Mentor)
        .join(Course, Course.id == Enrollment.course_id)
        .outerjoin(Mentor, Mentor.id == Course.mentor_id)
        .filter(Enrollment.student_id == student.id)
        .order_by(Enrollment.enrolled_at.desc())
        .all()
    )

    items = []
    for enr, course, mentor in rows:
        items.append({
            "id": enr.id,
            "course_id": course.id if course else None,
            "course_title": course.title if course else None,
            "mentor_name": getattr(mentor, "full_name", None),
            "status": enr.status or "ONGOING",
            "enrolled_at": enr.enrolled_at.isoformat() if enr.enrolled_at else None,
        })

    return jsonify({
        "student_id": student.id,
        "items": items,
    })
# ------------------------- Student Skills APIs (JSON for SPA) -------------------------

@api_bp.get("/students/<int:student_id>/skills")
@api_auth_required()
def api_student_skills_list(student_id):
    """لیست مهارت‌های یک دانشجو برای فرانت Vue"""
    s = Student.query.get_or_404(student_id)

    q = (
        StudentSkill.query.filter_by(student_id=s.id)
        .join(Skill, StudentSkill.skill_id == Skill.id)
        .order_by(StudentSkill.created_at.desc())
    )

    items = []
    for ss in q.all():
        sk = ss.skill
        items.append({
            "id": ss.id,
            "skill_id": sk.id,
            "type": (sk.type or "").upper(),       # TECH / SOFT
            "name": sk.name,
            "date_label": ss.date_label,
            "hours": ss.hours,
        })

    return jsonify({
        "items": items,
        "total": len(items),
    }), 200


@api_bp.post("/students/<int:student_id>/skills")
@api_auth_required()
def api_student_skills_add(student_id):
    """افزودن یک مهارت برای دانشجو (فنی یا نرم)"""
    s = Student.query.get_or_404(student_id)
    data = request.get_json(silent=True) or {}

    stype = (data.get("type") or "").upper()
    name = (data.get("name") or "").strip()
    date_label = (data.get("date_label") or "").strip()
    hours = data.get("hours")

    if stype not in ("TECH", "SOFT") or not name:
        return jsonify({"ok": False, "error": "invalid_input"}), 400

    # پیدا کردن/ساخت خود Skill
    skill = Skill.query.filter_by(name=name, type=stype).first()
    if not skill:
        skill = Skill(name=name, type=stype)
        db.session.add(skill)
        db.session.flush()  # تا skill.id داشته باشیم

    # لینک دانشجو ↔ مهارت
    ss = StudentSkill(
        student_id=s.id,
        skill_id=skill.id,
        date_label=date_label or None,
        hours=int(hours) if hours else None,
    )
    db.session.add(ss)
    db.session.commit()

    item = {
        "id": ss.id,
        "skill_id": skill.id,
        "type": (skill.type or "").upper(),
        "name": skill.name,
        "date_label": ss.date_label,
        "hours": ss.hours,
    }

    return jsonify({"ok": True, "item": item}), 201


@api_bp.delete("/students/<int:student_id>/skills/<int:ss_id>")
@api_auth_required()
def api_student_skills_delete(student_id, ss_id):
    """حذف یک مهارت از پروفایل دانشجو"""
    s = Student.query.get_or_404(student_id)
    ss = StudentSkill.query.filter_by(id=ss_id, student_id=s.id).first_or_404()

    db.session.delete(ss)
    db.session.commit()
    return jsonify({"ok": True}), 200

@api_bp.get("/students/<int:student_id>/finance/summary")
@api_auth_required()
def api_student_finance_summary(student_id: int):
    """
    خلاصه مالی دانشجو بر اساس منطق فعلی finance:
    - برای هر Enrollment دانشجو: (fee, paid) از تابع _enrollment_financials
    - خروجی:
      {
        "items": [
          {
            "enrollment_id": ...,
            "course_id": ...,
            "course_title": ...,
            "fee": ...,
            "paid": ...,
            "balance": ...
          },
          ...
        ],
        "totals": {
          "fee": ...,
          "paid": ...,
          "balance": ...
        }
      }
    """
    # اگر Enrollment در این پروژه نباشد، خروجی خالی
    if not Enrollment:
        return jsonify({
            "items": [],
            "totals": {"fee": 0, "paid": 0, "balance": 0},
        })

    student = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    q = Enrollment.query.filter(Enrollment.student_id == student.id)
    if hasattr(Enrollment, "status"):
        q = q.filter(Enrollment.status.in_(("ACTIVE", "ONGOING", "PENDING")))

    enrollments = q.all()

    items = []
    sum_fee = 0
    sum_paid = 0

    for en in enrollments:
        try:
            fee, paid = _enrollment_financials(en)
        except Exception:
            fee, paid = 0, 0

        sum_fee += fee
        sum_paid += paid

        course = getattr(en, "course", None)
        course_title = getattr(course, "title", None) if course is not None else None

        items.append(
            {
                "enrollment_id": getattr(en, "id", None),
                "course_id": getattr(en, "course_id", None),
                "course_title": course_title,
                "fee": int(fee),
                "paid": int(paid),
                "balance": int(max(fee - paid, 0)),
            }
        )

    totals = {
        "fee": int(sum_fee),
        "paid": int(sum_paid),
        "balance": int(max(sum_fee - sum_paid, 0)),
    }

    return jsonify({"items": items, "totals": totals}), 200

@api_bp.get("/students/<int:student_id>/payments")
@api_auth_required()
def api_student_payments_list(student_id: int):
    """
    لیست پرداخت‌ها/دریافت‌های مربوط به این دانشجو از جدول payments.
    GET /api/students/<id>/payments
    """
    student = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    q = Payment.query.filter(Payment.student_id == student.id)

    # مرتب‌سازی: ابتدا بر اساس paid_at، بعد created_at
    try:
        q = q.order_by(
            Payment.paid_at.desc().nullslast(),
            Payment.created_at.desc().nullslast(),
        )
    except Exception:
        q = q.order_by(Payment.id.desc())

    payments = q.all()

    items = []
    for p in payments:
        course = None
        if getattr(p, "course_id", None):
            try:
                course = Course.query.get(p.course_id)
            except Exception:
                course = None
        items.append(_payment_to_dict_api(p, course))

    return jsonify({"items": items, "total": len(items)}), 200
@api_bp.post("/students/<int:student_id>/payments")
@api_auth_required()
def api_student_payment_create(student_id: int):
    """
    ساخت یک پرداخت/دریافت برای دانشجو.
    بدنهٔ JSON ورودی:
      {
        "title": "شهریه ترم ۱",
        "amount": 12000000,
        "type": "IN" | "OUT",
        "course_id": 3   # اختیاری
      }
    """
    student = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    amount_raw = data.get("amount")
    pay_type = (data.get("type") or "IN").upper().strip()
    course_id = data.get("course_id")

    try:
        amount = float(amount_raw)
    except Exception:
        amount = 0.0

    if not title or amount <= 0:
        return jsonify({"ok": False, "error": "عنوان و مبلغ معتبر الزامی است."}), 400

    if pay_type not in ("IN", "OUT"):
        pay_type = "IN"

    p = Payment()
    p.student_id = student.id
    if course_id:
        try:
            p.course_id = int(course_id)
        except Exception:
            p.course_id = None

    p.title = title
    p.amount = amount
    p.status = "paid"

    # kind را طوری تنظیم می‌کنیم که با منطق KPIهای فعلی سازگار باشد
    if pay_type == "IN":
        p.kind = "tuition"    # دریافتی شهریه
    else:
        p.kind = "refund"     # برگشت/تخفیف/هزینهٔ معکوس

    try:
        p.paid_at = datetime.utcnow()
    except Exception:
        p.paid_at = None

    db.session.add(p)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"ok": False, "error": "ثبت تراکنش ناموفق بود."}), 500

    return jsonify({"ok": True, "id": p.id, "item": _payment_to_dict_api(p)}), 201
@api_bp.delete("/students/<int:student_id>/payments/<int:payment_id>")
@api_auth_required()
def api_student_payment_delete(student_id: int, payment_id: int):
    """
    حذف یک Payment متعلق به دانشجو.
    """
    student = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    p = (
        Payment.query
        .filter(Payment.id == payment_id, Payment.student_id == student.id)
        .first_or_404()
    )

    db.session.delete(p)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"ok": False, "error": "حذف تراکنش ناموفق بود."}), 500

    return jsonify({"ok": True}), 200

@api_bp.post("/students/<int:student_id>/installments")
@api_auth_required()
def api_student_installment_create(student_id: int):
    """
    ساخت یک ردیف قسط برای دانشجو.

    Body (JSON مثال):

    {
      "title": "قسط ۱",
      "amount_total": 3150000,
      "due_date": "2025-12-01",
      "course_id": 3,          # اختیاری، برای وصل‌کردن به دوره
      "plan_id": 10,           # اختیاری، برای اضافه‌کردن به یک پلن موجود
      "plan_title": "پلن جدید" # اختیاری، اگر plan_id ندادیم و می‌خواهیم پلن تازه بسازیم
    }
    """
    # اگر مدل‌ها در این پروژه فعال نباشند
    if not InstallmentPlan or not Installment:
        return jsonify({"ok": False, "error": "Installments not supported"}), 400

    student = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    amount_raw = data.get("amount_total") or data.get("amount")
    course_id = data.get("course_id")
    plan_id = data.get("plan_id")
    plan_title = (data.get("plan_title") or "").strip()
    due_date_raw = data.get("due_date")

    # اعتبارسنجی حداقلی
    try:
        amount = float(amount_raw)
    except Exception:
        amount = 0.0

    if not title or amount <= 0:
        return jsonify({"ok": False, "error": "عنوان و مبلغ معتبر الزامی است."}), 400

    # 🔹 پیدا کردن / ساختن InstallmentPlan
    plan = None

    # ۱) اگر plan_id مستقیم داده شده باشد
    if plan_id:
        try:
            plan = (
                InstallmentPlan.query
                .filter(InstallmentPlan.id == int(plan_id))
                .filter(InstallmentPlan.student_id == student.id)
                .first()
            )
        except Exception:
            plan = None

    # ۲) اگر plan_id نبود، ولی course_id هست: سعی می‌کنیم پلن موجود را برای همین دانشجو + دوره پیدا کنیم
    if not plan and course_id:
        try:
            plan = (
                InstallmentPlan.query
                .filter(InstallmentPlan.student_id == student.id)
                .filter(InstallmentPlan.course_id == int(course_id))
                .first()
            )
        except Exception:
            plan = None

    # ۳) اگر هنوز پلنی پیدا نشد، پلن جدید می‌سازیم
    if not plan:
        title_default = plan_title or f"پلن اقساط دانشجو {getattr(student, 'first_name', '')} {getattr(student, 'last_name', '')}".strip()
        if not title_default:
            title_default = "پلن اقساط"

        plan = InstallmentPlan(
            student_id=student.id,
            title=title_default,
        )
        if course_id:
            try:
                plan.course_id = int(course_id)
            except Exception:
                plan.course_id = None

        plan.total_amount = 0
        plan.installments_count = 0
        db.session.add(plan)
        db.session.flush()  # تا plan.id داشته باشیم

    # 🔹 تعیین شماره قسط (seq)
    existing_count = (
        Installment.query
        .filter(
            (Installment.plan_id == plan.id)
            | (getattr(Installment, "installment_plan_id", None) == plan.id)
        )
        .count()
    )
    seq = existing_count + 1

    # 🔹 تبدیل تاریخ سررسید
    due_date = None
    if due_date_raw:
        try:
            # قبول فرمت yyyy-mm-dd یا iso
            due_date = datetime.fromisoformat(due_date_raw).date()
        except Exception:
            due_date = None

    # 🔹 ساخت خود قسط
    inst = Installment(
        plan_id=getattr(plan, "id", None),
        seq=seq,
        title=title,
        amount_base=amount,
        cheque_fee_amount=0,
        amount_total=amount,
        status="PENDING",
    )
    if hasattr(inst, "due_date"):
        inst.due_date = due_date

    db.session.add(inst)

    # آپدیت خلاصهٔ پلن
    try:
        plan.total_amount = (plan.total_amount or 0) + amount
        plan.installments_count = (plan.installments_count or 0) + 1
    except Exception:
        pass

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"ok": False, "error": "ثبت قسط ناموفق بود."}), 500

    return jsonify({
        "ok": True,
        "item": _installment_to_dict_api(inst),
    }), 201

@api_bp.post("/installments/<int:installment_id>/status")
@api_auth_required()
def api_installment_update_status(installment_id: int):
    """
    تغییر وضعیت یک قسط
    POST /api/installments/<id>/status
    Body (JSON):
      {
        "status": "PAID" | "PENDING" | "CANCELLED"
      }
    """
    inst = Installment.query.get_or_404(installment_id)

    payload = request.get_json(silent=True) or {}
    new_status = (payload.get("status") or "").upper()

    allowed = {"PENDING", "PAID", "CANCELLED"}
    if new_status not in allowed:
        return jsonify({"error": "status نامعتبر است"}), 400

    inst.status = new_status

    # اگر در مدل ستون paid_at داری، این منطق قشنگه:
    if hasattr(Installment, "paid_at"):
        if new_status == "PAID":
            # اگر فرانت تاریخ خاصی فرستاد، از همون استفاده کن
            paid_at_raw = payload.get("paid_at")
            if paid_at_raw:
                try:
                    inst.paid_at = datetime.fromisoformat(paid_at_raw)
                except Exception:
                    inst.paid_at = datetime.utcnow()
            else:
                inst.paid_at = datetime.utcnow()
        else:
            # اگر دوباره Pending/Cancelled شد، می‌تونیم paid_at را خالی کنیم
            inst.paid_at = None

    db.session.commit()
    return jsonify(_installment_to_dict_api(inst)), 200
