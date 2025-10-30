# app/blueprints/courses/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import or_, and_, func
from datetime import datetime, date as _date, timedelta as _td
from app.extensions import db
from app.models.course import Course
from app.models.mentor import Mentor
from app.utils.media import save_uploaded_image
from app.models.course_session import CourseSession, Attendance
from app.models.core import Student
from app.models.enrollment import Enrollment

bp = Blueprint("courses", __name__, url_prefix="/courses")

_MAP_DAYS = {"SA": 5, "SU": 6, "MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4}

# ============================
# لیست دوره‌ها
# ============================
@bp.get("/", endpoint="index")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    page = int(request.args.get("page") or 1)
    per_page = 12

    base = Course.query
    if q:
        like = f"%{q}%"
        base = base.filter(or_(Course.title.like(like), Course.mentor_name.like(like)))

    pagination = base.order_by(Course.id.desc()).paginate(page=page, per_page=per_page)
    items = pagination.items
    return render_template("courses/index.html", items=items, pagination=pagination, q=q)

# ============================
# ساخت دوره
# ============================
@bp.get("/new", endpoint="new")
@login_required
def new_form():
    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    return render_template("courses/form.html", c=None, mentors=mentors, mode="create")

@bp.post("/", endpoint="create")
@login_required
def create():
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("نام دوره الزامی است.", "error")
        return redirect(url_for("courses.new"))

    c = Course(
        title=title,
        description=(request.form.get("description") or "").strip() or None,
        mentor_id=(int(request.form.get("mentor_id")) if request.form.get("mentor_id") else None),
        start_date=_parse_date(request.form.get("start_date")),
        end_date=_parse_date(request.form.get("end_date")),
        schedule_type=(request.form.get("schedule_type") or "CUSTOM"),
        fee_per_student=_to_int(request.form.get("fee_per_student")),
        installment_enabled=(request.form.get("installment_enabled") == "1"),
        mentor_share_percent=_to_float(request.form.get("mentor_share_percent")),
        status=(request.form.get("status") or "ACTIVE"),
    )

    if c.mentor_id:
        m = Mentor.query.get(c.mentor_id)
        c.mentor_name = (m.full_name or (f"{m.first_name or ''} {m.last_name or ''}".strip())) if m else None

    c.sessions_json = _safe_json(request.form.get("sessions_json")) or None

    wdays = _safe_json(request.form.get("weekly_days_json")) or []
    c.weekly_days_json = wdays or None
    sdays_csv = ",".join(wdays) if wdays else None
    if hasattr(Course, "schedule_days"):
        c.schedule_days = sdays_csv

    raw_pair = (request.form.get("pair_odd") or "").upper().strip() or None
    mapped_pattern = "EVEN" if raw_pair == "PAIR" else ("ODD" if raw_pair == "ODD" else None)
    c.pair_odd = raw_pair
    if hasattr(Course, "schedule_pattern"):
        c.schedule_pattern = mapped_pattern

    c.installments_json = _safe_json(request.form.get("installments_json")) or None

    ok, err = _validate_schedule_inputs_for(c)
    if not ok:
        flash(err, "error")
        return redirect(url_for("courses.new"))

    cover_file = request.files.get("cover_image")
    cover_rel = save_uploaded_image(cover_file, subdir="courses")
    if cover_rel:
        c.cover_image = cover_rel

    db.session.add(c)
    db.session.commit()
    flash("دوره با موفقیت ایجاد شد.", "success")
    return redirect(url_for("courses.edit", id=c.id))

# ============================
# ویرایش دوره
# ============================
@bp.get("/<int:id>/edit")
@login_required
def edit(id):
    c = Course.query.get_or_404(id)
    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    return render_template("courses/form.html", c=c, mentors=mentors, mode="edit")

@bp.post("/<int:id>/edit")
@login_required
def update(id):
    c = Course.query.get_or_404(id)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("نام دوره الزامی است.", "error")
        return redirect(url_for("courses.edit", id=c.id))

    c.title = title
    c.description = (request.form.get("description") or "").strip() or None
    c.mentor_id = (int(request.form.get("mentor_id")) if request.form.get("mentor_id") else None)
    c.start_date = _parse_date(request.form.get("start_date"))
    c.end_date = _parse_date(request.form.get("end_date"))
    c.schedule_type = (request.form.get("schedule_type") or "CUSTOM")
    c.fee_per_student = _to_int(request.form.get("fee_per_student"))
    c.installment_enabled = (request.form.get("installment_enabled") == "1")
    c.mentor_share_percent = _to_float(request.form.get("mentor_share_percent"))
    c.status = (request.form.get("status") or "ACTIVE")

    c.mentor_name = None
    if c.mentor_id:
        m = Mentor.query.get(c.mentor_id)
        c.mentor_name = (m.full_name or (f"{m.first_name or ''} {m.last_name or ''}".strip())) if m else None

    c.sessions_json = _safe_json(request.form.get("sessions_json")) or None

    wdays = _safe_json(request.form.get("weekly_days_json")) or []
    c.weekly_days_json = wdays or None
    sdays_csv = ",".join(wdays) if wdays else None
    if hasattr(Course, "schedule_days"):
        c.schedule_days = sdays_csv

    raw_pair = (request.form.get("pair_odd") or "").upper().strip() or None
    mapped_pattern = "EVEN" if raw_pair == "PAIR" else ("ODD" if raw_pair == "ODD" else None)
    c.pair_odd = raw_pair
    if hasattr(Course, "schedule_pattern"):
        c.schedule_pattern = mapped_pattern

    c.installments_json = _safe_json(request.form.get("installments_json")) or None

    ok, err = _validate_schedule_inputs_for(c)
    if not ok:
        flash(err, "error")
        return redirect(url_for("courses.edit", id=c.id))

    cover_file = request.files.get("cover_image")
    if cover_file and getattr(cover_file, "filename", ""):
        cover_rel = save_uploaded_image(cover_file, subdir="courses")
        if cover_rel:
            c.cover_image = cover_rel

    db.session.commit()
    flash("دوره به‌روزرسانی شد.", "success")
    return redirect(url_for("courses.edit", id=c.id))

# ============================
# بایگانی / حذف
# ============================
@bp.post("/<int:id>/archive")
@login_required
def archive(id):
    c = Course.query.get_or_404(id)
    c.status = "ARCHIVED"
    db.session.commit()
    flash("دوره بایگانی شد.", "info")
    return redirect(url_for("courses.index"))

@bp.post("/<int:id>/delete")
@login_required
def delete(id):
    c = Course.query.get_or_404(id)
    db.session.delete(c)
    db.session.commit()
    flash("دوره حذف شد.", "info")
    return redirect(url_for("courses.index"))

# ============================
# جلسات / حضور و غیاب
# ============================
@bp.route("/<int:course_id>/sessions")
@login_required
def sessions_view(course_id):
    return render_template("courses/sessions.html", course_id=course_id)

@bp.route("/<int:course_id>/sessions.json")
@login_required
def sessions_json(course_id):
    qs = (
        CourseSession.query
        .filter_by(course_id=course_id)
        .order_by(CourseSession.session_date)
        .all()
    )
    items = [{
        "id": s.id,
        "session_date": s.session_date.isoformat(),
        "start_time": s.start_time.isoformat() if s.start_time else None,
        "end_time": s.end_time.isoformat() if s.end_time else None,
        "room": s.room,
        "note": s.note
    } for s in qs]
    return jsonify(items)

@bp.route("/<int:course_id>/sessions/<int:session_id>/attendances")
@login_required
def session_attendances(course_id, session_id):
    rows = Attendance.query.filter_by(session_id=session_id).all()
    items = [{
        "id": a.id,
        "student_id": a.student_id,
        "student_name": (a.student.first_name + " " + (a.student.last_name or "")) if a.student else None,
        "status": a.status,
        "note": a.note
    } for a in rows]
    return jsonify(items)

@bp.route("/<int:course_id>/sessions/<int:session_id>/attendances", methods=["POST"])
@login_required
def add_attendance(course_id, session_id):
    data = request.json or {}
    student_id = data.get("student_id")
    status = data.get("status", "PRESENT")
    note = data.get("note")
    if not student_id:
        return jsonify({"ok": False, "error": "student_id required"}), 400
    a = Attendance.query.filter_by(session_id=session_id, student_id=student_id).first()
    if not a:
        a = Attendance(session_id=session_id, student_id=student_id, status=status, note=note)
        db.session.add(a)
    else:
        a.status = status
        a.note = note
    db.session.commit()
    return jsonify({"ok": True, "id": a.id})

@bp.post("/<int:course_id>/sessions/preview")
@login_required
def sessions_preview(course_id):
    c = Course.query.get_or_404(course_id)
    ok, err = _validate_schedule_inputs_for(c)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    body = request.get_json(silent=True) or {}
    exclude = _norm_dates_str_list(body.get("exclude") or [])

    st = (c.schedule_type or "DATES").upper()
    days = set()

    if st == "WEEKLY":
        days = _generate_dates_weekly(c, exclude)
    else:
        raw_dates = body.get("sessions_json") or []
        cand = _norm_dates_str_list(raw_dates)
        for d in cand:
            if c.start_date <= d <= c.end_date and d not in exclude:
                days.add(d)

    res = sorted(days)
    return jsonify({"ok": True, "dates": [d.isoformat() for d in res], "count": len(res)})

@bp.post("/<int:course_id>/sessions/generate")
@login_required
def api_generate_sessions(course_id):
    c = Course.query.get_or_404(course_id)

    ok, err = _validate_schedule_inputs_for(c)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    existing = CourseSession.query.filter_by(course_id=course_id).count()
    if existing:
        return jsonify({"ok": False, "error": "جلسات قبلاً ساخته شده"}), 409

    body = request.get_json(silent=True) or {}
    if not body and request.form:
        import json
        try:
            body = json.loads(request.form.get("payload") or "{}")
        except Exception:
            body = {}

    exclude = _norm_dates_str_list(body.get("exclude") or [])

    st = (c.schedule_type or "DATES").upper()
    final_days = set()

    if st == "WEEKLY":
        final_days = _generate_dates_weekly(c, exclude)
    else:
        raw_dates = body.get("sessions_json") or []
        cand = _norm_dates_str_list(raw_dates)
        for d in cand:
            if c.start_date <= d <= c.end_date and d not in exclude:
                final_days.add(d)

    if not final_days:
        return jsonify({"ok": False, "error": "هیچ تاریخی برای ایجاد جلسه یافت نشد."}), 400

    for d in sorted(final_days):
        db.session.add(CourseSession(course_id=course_id, session_date=d))

    db.session.commit()
    return jsonify({"ok": True, "created": len(final_days)})

# ============================
# صفحه حضور و غیاب (HTML)
# ============================
@bp.route("/<int:course_id>/attendance", methods=["GET"])
@login_required
def attendance_page(course_id):
    course = Course.query.get_or_404(course_id)
    sessions = (
        CourseSession.query
        .filter(CourseSession.course_id == course.id)
        .order_by(CourseSession.session_date.asc(), CourseSession.start_time.asc())
        .all()
    )

    if not sessions:
        flash("برای این دوره هنوز جلسه‌ای ساخته نشده. ابتدا از «تولید جلسات از برنامه» استفاده کنید.", "warning")
        return redirect(url_for("courses.edit", id=course.id))

    selected_id = request.args.get("session_id", type=int) or sessions[0].id
    selected_session = next((s for s in sessions if s.id == selected_id), sessions[0])

    enrolls = (
        Enrollment.query
        .filter(and_(Enrollment.course_id == course.id, Enrollment.status == "ACTIVE"))
        .all()
    )
    student_ids = [e.student_id for e in enrolls]

    students = (
        Student.query
        .filter(Student.id.in_(student_ids) if student_ids else False)
        .order_by(Student.last_name.asc(), Student.first_name.asc())
        .all()
    )

    existing = (
        Attendance.query
        .filter(and_(Attendance.session_id == selected_session.id,
                     Attendance.student_id.in_(student_ids) if student_ids else False))
        .all()
    )
    att_map = {a.student_id: a for a in existing}

    return render_template(
        "courses/attendance.html",
        course=course,
        sessions=sessions,
        selected_session=selected_session,
        students=students,
        att_map=att_map
    )

@bp.route("/<int:course_id>/attendance", methods=["POST"])
@login_required
def attendance_save(course_id):
    course = Course.query.get_or_404(course_id)
    session_id = request.form.get("session_id", type=int)
    if not session_id:
        flash("شناسه جلسه نامعتبر است.", "error")
        return redirect(url_for("courses.attendance_page", course_id=course.id))

    session_obj = CourseSession.query.filter_by(id=session_id, course_id=course.id).first()
    if not session_obj:
        flash("جلسه یافت نشد.", "error")
        return redirect(url_for("courses.attendance_page", course_id=course.id))

    enrolls = (
        Enrollment.query
        .filter(and_(Enrollment.course_id == course.id, Enrollment.status == "ACTIVE"))
        .all()
    )
    student_ids = [e.student_id for e in enrolls]

    existing = (
        Attendance.query
        .filter(and_(Attendance.session_id == session_id,
                     Attendance.student_id.in_(student_ids) if student_ids else False))
        .all()
    )
    existing_map = {(a.session_id, a.student_id): a for a in existing}

    created, updated = 0, 0
    for sid in student_ids:
        status = (request.form.get(f"status_{sid}", "PRESENT") or "PRESENT").strip()
        note = (request.form.get(f"note_{sid}", "") or "").strip() or None

        key = (session_id, sid)
        if key in existing_map:
            a = existing_map[key]
            if a.status != status or (a.note or "") != (note or ""):
                a.status = status
                a.note = note
                updated += 1
        else:
            a = Attendance(session_id=session_id, student_id=sid, status=status, note=note)
            db.session.add(a)
            created += 1

    db.session.commit()
    flash(f"حضور و غیاب ذخیره شد. (جدید: {created}، به‌روزشده: {updated})", "success")
    return redirect(url_for("courses.attendance_page", course_id=course.id, session_id=session_id))

# ============================
# Enrollment (API ساده)
# ============================
@bp.get("/<int:course_id>/enrollments")
@login_required
def api_list_enrollments(course_id):
    ens = (
        db.session.query(Enrollment)
        .filter(Enrollment.course_id == course_id)
        .join(Student, Student.id == Enrollment.student_id)
        .order_by(Student.last_name.asc(), Student.first_name.asc(), Student.id.asc())
        .all()
    )

    def _full_name(st):
        fn = (st.first_name or "").strip()
        ln = (st.last_name or "").strip()
        full = (fn + " " + ln).strip()
        return full or f"دانشجو #{st.id}"

    return jsonify([
        {"id": e.id, "student_id": e.student_id, "student_name": _full_name(e.student)}
        for e in ens
    ])

@bp.post("/<int:course_id>/enrollments")
@login_required
def api_add_enrollment(course_id):
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

    exists = Enrollment.query.filter_by(course_id=course_id, student_id=student_id).first()
    if exists:
        return jsonify({"ok": False, "error": "قبلاً ثبت شده"}), 409

    now_utc = datetime.utcnow()
    e = Enrollment(course_id=course_id, student_id=student_id, status="ACTIVE")
    if hasattr(Enrollment, "enrolled_at"):
        setattr(e, "enrolled_at", now_utc)
    if hasattr(Enrollment, "joined_at"):
        setattr(e, "joined_at", now_utc)

    db.session.add(e)
    db.session.commit()
    return jsonify({"ok": True, "id": e.id})

@bp.delete("/<int:course_id>/enrollments/<int:en_id>")
@login_required
def api_delete_enrollment(course_id, en_id):
    e = Enrollment.query.filter_by(id=en_id, course_id=course_id).first_or_404()
    db.session.delete(e)
    db.session.commit()
    return jsonify({"ok": True})

# ============================
# Students: available for enrollment
# ============================
@bp.get("/<int:course_id>/students/available")
@login_required
def students_available(course_id):
    Course.query.get_or_404(course_id)

    q = (request.args.get("q") or "").strip()
    limit = request.args.get("limit", type=int) or 50
    limit = max(1, min(limit, 100))

    enrolled_ids_subq = db.session.query(Enrollment.student_id).filter(
        Enrollment.course_id == course_id
    ).subquery()

    qry = Student.query.filter(~Student.id.in_(enrolled_ids_subq))

    if q:
        like = f"%{q}%"
        id_filter = (Student.id == int(q)) if q.isdigit() else False
        qry = qry.filter(
            or_(
                id_filter,
                Student.first_name.ilike(like),
                Student.last_name.ilike(like),
                Student.phone.ilike(like),
            )
        )

    students = (
        qry.order_by(Student.last_name.asc(), Student.first_name.asc())
        .limit(limit).all()
    )

    def label_for(s):
        full = f"{(s.first_name or '').strip()} {(s.last_name or '').strip()}".strip() or f"دانشجو #{s.id}"
        phone = f" — {s.phone}" if getattr(s, "phone", None) else ""
        return f"{full}{phone} (ID {s.id})"

    return jsonify([{"id": s.id, "label": label_for(s)} for s in students])

@bp.get("/test/datepicker")
def test_datepicker():
    return render_template("test_datepicker.html")

# ============================
# Students JSON (برای UI فرم)
# ============================
def _student_dict(s: Student):
    name = ((s.first_name or '').strip() + ' ' + (s.last_name or '').strip()).strip()
    if not name and hasattr(s, "full_name"):
        name = (s.full_name or "").strip()
    return {"id": s.id, "name": name or "—", "email": s.email or "", "phone": s.phone or ""}

@bp.get("/<int:course_id>/students/json")
@login_required
def students_json(course_id: int):
    course = Course.query.get_or_404(course_id)

    enrolled = (
        Student.query.join(Enrollment, Enrollment.student_id == Student.id)
        .filter(Enrollment.course_id == course.id)
        .order_by(Student.id.desc())
        .all()
    )

    enrolled_ids_q = db.session.query(Enrollment.student_id).filter_by(course_id=course.id)
    q = (request.args.get("q") or "").strip()
    available_q = Student.query.filter(~Student.id.in_(enrolled_ids_q))
    if q:
        like = f"%{q}%"
        full = (func.trim(func.coalesce(Student.first_name, "")) + " " + func.trim(func.coalesce(Student.last_name, "")))
        available_q = available_q.filter(
            Student.first_name.ilike(like) |
            Student.last_name.ilike(like)  |
            full.ilike(like)               |
            Student.email.ilike(like)      |
            Student.phone.ilike(like)
        )
    available = available_q.order_by(Student.id.desc()).limit(50).all()

    return jsonify({
        "course_id": course.id,
        "enrolled":  [_student_dict(s) for s in enrolled],
        "available": [_student_dict(s) for s in available],
        "count": {"enrolled": len(enrolled), "available": len(available)},
    })

@bp.post("/<int:course_id>/students/enroll")
@login_required
def students_enroll(course_id: int):
    course = Course.query.get_or_404(course_id)
    sid = request.form.get("student_id", type=int)
    if not sid:
        return jsonify({"ok": False, "error": "student_id لازم است"}), 400

    exists = Enrollment.query.filter_by(course_id=course.id, student_id=sid).first()
    if exists:
        return jsonify({"ok": True, "message": "قبلاً ثبت شده"}), 200

    db.session.add(Enrollment(course_id=course.id, student_id=sid))
    db.session.commit()
    return jsonify({"ok": True})

@bp.post("/<int:course_id>/students/unenroll")
@login_required
def students_unenroll(course_id: int):
    course = Course.query.get_or_404(course_id)
    sid = request.form.get("student_id", type=int)
    if not sid:
        return jsonify({"ok": False, "error": "student_id لازم است"}), 400

    enr = Enrollment.query.filter_by(course_id=course.id, student_id=sid).first()
    if not enr:
        return jsonify({"ok": True, "message": "قبلاً حذف شده/یافت نشد"}), 200

    db.session.delete(enr)
    db.session.commit()
    return jsonify({"ok": True})

# ============================
# Helpers
# ============================
def _to_int(x):
    try:
        s = str(x or "0").replace(",", "").replace("٬", "").strip()
        return int(float(s))
    except Exception:
        return 0

def _to_float(x):
    try:
        s = str(x or "0").replace(",", "").replace("٬", "").strip()
        return float(s)
    except Exception:
        return None

def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _safe_json(s):
    if not s:
        return None
    import json
    try:
        return json.loads(s)
    except Exception:
        return None

def _norm_date_str(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def _norm_dates_str_list(raw):
    if not raw:
        return set()
    out = set()
    for it in raw:
        if isinstance(it, dict):
            d = _norm_date_str(it.get("date"))
        else:
            d = _norm_date_str(str(it))
        if d:
            out.add(d)
    return out

def _validate_schedule_inputs_for(course) -> tuple[bool, str]:
    if not (course.start_date and course.end_date):
        return False, "تاریخ شروع/پایان دوره تنظیم نشده است."
    if course.start_date > course.end_date:
        return False, "تاریخ پایان نباید قبل از تاریخ شروع باشد."

    st = (course.schedule_type or "CUSTOM").upper()
    if st == "WEEKLY":
        days = (course.schedule_days or "").strip()
        patt = (course.schedule_pattern or "").strip().upper()
        has_days = bool(days)
        has_pair = patt in ("EVEN", "ODD")
        if has_days == has_pair:
            return False, "در زمان‌بندی هفتگی، باید دقیقاً یکی از «روزهای هفته» یا «الگوی زوج/فرد» را انتخاب کنید."
    return True, ""

def _generate_dates_weekly(c: Course, exclude: set[_date] | None = None) -> set[_date]:
    exclude = exclude or set()
    start, end = c.start_date, c.end_date
    out = set()

    days_csv = (c.schedule_days or "").strip()
    patt = (c.schedule_pattern or "").upper().strip()

    if days_csv:
        wanted = {_MAP_DAYS[d] for d in days_csv.split(",") if d in _MAP_DAYS}
        d = start
        while d <= end:
            if (d.weekday() in wanted) and (d not in exclude):
                out.add(d)
            d += _td(days=1)
        return out

    if patt in ("EVEN", "ODD"):
        d = start
        while d <= end:
            delta = (d - start).days
            ok = (delta % 2 == 0 and patt == "EVEN") or (delta % 2 == 1 and patt == "ODD")
            if ok and d not in exclude:
                out.add(d)
            d += _td(days=1)
        return out

    return out

def _pick_ids(raw_list):
    ids = set()
    for it in (raw_list or []):
        try:
            if isinstance(it, dict):
                ids.add(int(it.get("id")))
            else:
                ids.add(int(it))
        except Exception:
            continue
    return ids

def _serialize_student(st: Student):
    return {
        "id": st.id,
        "name": f"{st.first_name or ''} {st.last_name or ''}".strip(),
        "email": st.email,
        "phone": st.phone,
    }
