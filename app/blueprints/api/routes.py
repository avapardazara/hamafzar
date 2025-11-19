from datetime import datetime

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
from app.models.mentor_payment import MentorPayment  # 👈 این خط جدید
from app.models.course_session import CourseSession, Attendance



try:
    from app.models.enrollment import Enrollment
except ImportError:  # اگر فعلاً نداری، بعداً پرش می‌کنیم
    Enrollment = None

#---------------financeHelpers-------------------
def session_to_dict(s: CourseSession, stats: dict | None = None) -> dict:
    """خروجی استاندارد جلسه برای فرانت (همون چیزی که تو تب Sessions استفاده می‌کنیم)."""
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

    return {
        "id": getattr(s, "id", None),
        "course_id": getattr(s, "course_id", None),
        "session_date": session_date,
        "start_time": getattr(s, "start_time", None),
        "end_time": getattr(s, "end_time", None),
        "duration_minutes": getattr(s, "duration_minutes", None),
        "status": getattr(s, "status", None) or "PLANNED",
        "stats": {
            "total": stats.get("total", 0),
            "present": stats.get("present", 0),
            "absent": stats.get("absent", 0),
        },
    }


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

def _parse_date_param(raw: str | None):
    """
    ورودی خام مثل '2024-01-01' یا '2024/01/01' رو به date تبدیل می‌کند.
    اگر خالی/نامعتبر باشد None برمی‌گرداند.
    """
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
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
    پروفایل دانشجو (نسخه ساده؛ فعلاً فقط اطلاعات اصلی)
    GET /api/students/<id>
    """
    s = Student.query.filter_by(id=student_id, is_deleted=False).first_or_404()

    data = {
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
        "enrollments": [],
        "payments": [],
        "instalments": [],
    }

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
    form = request.form
    files = request.files

    title = (form.get("title") or "").strip()
    if not title:
        return jsonify({"error": "نام دوره الزامی است."}), 400

    course = Course(
        title=title,
        mentor_id=_to_int_or_none(form.get("mentor_id")),
        status=(form.get("status") or "ACTIVE").upper(),

        start_date=form.get("start_date") or None,
        end_date=form.get("end_date") or None,
        start_time=form.get("start_time") or None,
        end_time=form.get("end_time") or None,

        description=form.get("description") or None,

        fee_per_student=_to_float_or_none(form.get("fee_per_student")),
        mentor_share_percent=_to_float_or_none(form.get("mentor_share_percent")),

        schedule_type=form.get("schedule_type") or None,
        schedule_days=form.get("schedule_days") or None,
        schedule_pattern=form.get("schedule_pattern") or None,
        weekly_days_json=form.get("weekly_days_json") or None,
        sessions_json=form.get("sessions_json") or None,
    )

    if hasattr(Course, "capacity"):
        setattr(course, "capacity", _to_int_or_none(form.get("capacity")))
    if hasattr(Course, "category"):
        setattr(course, "category", form.get("category") or None)
    if hasattr(Course, "level"):
        setattr(course, "level", form.get("level") or None)

    db.session.add(course)
    db.session.commit()

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
    course = Course.query.get_or_404(course_id)

    if getattr(course, "is_deleted", False):
        return jsonify({"error": "not_found"}), 404

    form = request.form
    files = request.files

    title = (form.get("title") or "").strip()
    if title:
        course.title = title

    mentor_id = form.get("mentor_id")
    if mentor_id is not None:
        course.mentor_id = _to_int_or_none(mentor_id)

    status = form.get("status")
    if status:
        course.status = status.upper()

    for attr in ["start_date", "end_date", "start_time", "end_time", "description",
                 "schedule_type", "schedule_days", "schedule_pattern",
                 "weekly_days_json", "sessions_json"]:
        if attr in form:
            setattr(course, attr, form.get(attr) or None)

    if "fee_per_student" in form:
        course.fee_per_student = _to_float_or_none(form.get("fee_per_student"))
    if "mentor_share_percent" in form:
        course.mentor_share_percent = _to_float_or_none(form.get("mentor_share_percent"))

    if hasattr(Course, "capacity") and "capacity" in form:
        setattr(course, "capacity", _to_int_or_none(form.get("capacity")))
    if hasattr(Course, "category") and "category" in form:
        setattr(course, "category", form.get("category") or None)
    if hasattr(Course, "level") and "level" in form:
        setattr(course, "level", form.get("level") or None)

    file_storage = files.get("cover_image")
    if file_storage:
        delete_course_cover(course)
        rel = save_course_cover(file_storage, course.id)
        if rel:
            if hasattr(course, "cover_image"):
                course.cover_image = rel
            elif hasattr(course, "cover_path"):
                course.cover_path = rel

    db.session.commit()
    return jsonify(course_to_dict(course))


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


@api_bp.get("/courses/<int:course_id>/students")
@api_auth_required()
def api_course_students(course_id: int):
    """
    دانشجوهای ثبت‌نام‌شده در دوره
    GET /api/courses/<course_id>/students
    خروجی:
      { "items": [...], "total": ... }
    """
    if Enrollment is None:
        # اگر فعلاً مدل ثبت‌نام نداری، خالی برمی‌گردونیم تا فرانت کرش نکنه
        return jsonify({"items": [], "total": 0}), 200

    q = (
        db.session.query(Enrollment, Student)
        .join(Student, Enrollment.student_id == Student.id)
        .filter(Enrollment.course_id == course_id)
    )

    # اگر soft-delete یا وضعیت داشته باشی اینجا می‌تونی فیلتر کنی
    if hasattr(Enrollment, "is_deleted"):
        q = q.filter(Enrollment.is_deleted.is_(False))

    items = []
    for en, st in q.all():
        items.append(_enrollment_to_dict(en, st))

    return jsonify({"items": items, "total": len(items)}), 200


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