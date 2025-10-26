from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from datetime import datetime, date as _date, timedelta as _td
from sqlalchemy import func, and_
from sqlalchemy import or_
from app.extensions import db
from app.blueprints.attendance import bp
from app.models.course import Course
from app.models.course_session import CourseSession, Attendance
from app.models.enrollment import Enrollment
from app.models.core import Student


# -------------------------------
# Helpers
# -------------------------------
def _today_local() -> _date:
    # اگر پروژه تایمزون خاصی دارد، اینجا اعمال کن. فعلاً تاریخ لوکال ساده.
    return datetime.now().date()


def _ensure_attendance_for_session(course_id: int, session_id: int, default_status: str = "PRESENT") -> int:
    """
    به‌صورت تنبل، برای همه دانشجوهای ACTIVE این جلسه Attendance بسازد (اگر وجود ندارد).
    خروجی: تعداد رکوردهای تازه ساخته‌شده.
    """
    active_student_ids = [
        sid for (sid,) in db.session.query(Enrollment.student_id)
        .filter(Enrollment.course_id == course_id, Enrollment.status == "ACTIVE")
        .all()
    ]
    if not active_student_ids:
        return 0

    # رکوردهای موجود برای این جلسه
    existing = {
        sid for (sid,) in db.session.query(Attendance.student_id)
        .filter(Attendance.session_id == session_id, Attendance.student_id.in_(active_student_ids))
        .all()
    }

    created = 0
    for sid in active_student_ids:
        if sid in existing:
            continue
        db.session.add(Attendance(session_id=session_id, student_id=sid, status=default_status))
        created += 1

    if created:
        db.session.commit()

    return created


def _session_stats(session_id: int) -> dict:
    """
    شمارش وضعیت‌ها برای یک جلسه.
    """
    rows = (
        db.session.query(Attendance.status, func.count(Attendance.id))
        .filter(Attendance.session_id == session_id)
        .group_by(Attendance.status)
        .all()
    )
    stats = {"PRESENT": 0, "ABSENT": 0, "LATE": 0, "EXCUSED": 0}
    for st, cnt in rows:
        st = (st or "").upper()
        if st in stats:
            stats[st] = cnt
    total = sum(stats.values())
    stats["TOTAL"] = total
    return stats


def _course_sessions_with_stats(course_id: int):
    """
    لیست جلسات + آمار هر جلسه (برای صفحه تاریخچه).
    """
    sessions = (
        CourseSession.query
        .filter(CourseSession.course_id == course_id)
        .order_by(CourseSession.session_date.asc(), CourseSession.start_time.asc())
        .all()
    )
    items = []
    for s in sessions:
        st = _session_stats(s.id)
        items.append({
            "id": s.id,
            "date": s.session_date,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "room": s.room,
            "stats": st
        })
    return items


def _get_course_or_404(course_id: int) -> Course:
    return Course.query.get_or_404(course_id)


def _pick_session(course: Course, session_id: int | None) -> CourseSession | None:
    """
    اگر session_id داده نشده بود، اولویت:
      1) جلسهٔ امروز، اگر وجود دارد
      2) اولین جلسهٔ آینده
      3) اولین جلسهٔ دوره
    """
    q = (CourseSession.query
         .filter(CourseSession.course_id == course.id)
         .order_by(CourseSession.session_date.asc(), CourseSession.start_time.asc()))
    sessions = q.all()
    if not sessions:
        return None

    if session_id:
        s = next((x for x in sessions if x.id == session_id), None)
        return s or sessions[0]

    today = _today_local()
    # 1) امروز
    s_today = next((x for x in sessions if x.session_date == today), None)
    if s_today:
        return s_today
    # 2) آینده
    s_future = next((x for x in sessions if x.session_date > today), None)
    if s_future:
        return s_future
    # 3) fallback: اولین
    return sessions[0]


def _students_for_course(course_id: int):
    """
    دانشجوهای ACTIVE دوره برای نمایش نام و ... (مرتب‌سازی بر اساس نام/نام‌خانوادگی موجود).
    """
    ens = (
        db.session.query(Enrollment)
        .filter(and_(Enrollment.course_id == course_id, Enrollment.status == "ACTIVE"))
        .join(Student, Student.id == Enrollment.student_id)
        .order_by(Student.last_name.asc(), Student.first_name.asc(), Student.id.asc())
        .all()
    )
    # خروجی student objects
    return [e.student for e in ens if e.student]


# -------------------------------
# Routes
# -------------------------------

@bp.get("/<int:course_id>")
@login_required
def entry(course_id):
    """
    ورودی حضور و غیاب یک دوره → ریدایرکت به تاریخچه.
    """
    _get_course_or_404(course_id)
    return redirect(url_for("attendance.list", course_id=course_id))


@bp.get("/<int:course_id>/list")
@login_required
def list(course_id):
    """
    تاریخچه جلسات یک دوره با آمار خلاصه.
    """
    course = _get_course_or_404(course_id)
    items = _course_sessions_with_stats(course.id)
    return render_template("attendance/list.html", course=course, items=items)


@bp.get("/<int:course_id>/session/<int:session_id>")
@login_required
def session_view(course_id, session_id):
    """
    نمایش و lazy-create حضور و غیاب یک جلسه.
    """
    course = _get_course_or_404(course_id)
    s = CourseSession.query.filter_by(id=session_id, course_id=course.id).first_or_404()

    # Lazy-create فقط در روز جلسه (یا اگر ?force=1 آمده باشد برای تست دستی)
    force = request.args.get("force") == "1"
    if force or s.session_date == _today_local():
        _ensure_attendance_for_session(course.id, s.id, default_status="PRESENT")

    # دانشجوهای ACTIVE همین حالا
    students = _students_for_course(course.id)

    # رکوردهای موجود جلسه
    existing = Attendance.query.filter_by(session_id=s.id).all()
    att_map = {a.student_id: a for a in existing}

    return render_template(
        "attendance/session.html",
        course=course,
        session_obj=s,
        students=students,
        att_map=att_map
    )


@bp.post("/<int:course_id>/session/<int:session_id>")
@login_required
def session_save(course_id, session_id):
    """
    ذخیره فرم حضور و غیاب همون جلسه.
    """
    course = _get_course_or_404(course_id)
    s = CourseSession.query.filter_by(id=session_id, course_id=course.id).first_or_404()

    # دانشجوهای ACTIVE در لحظهٔ ذخیره
    students = _students_for_course(course.id)
    student_ids = [st.id for st in students]

    existing = (Attendance.query
                .filter(and_(Attendance.session_id == s.id,
                             Attendance.student_id.in_(student_ids) if student_ids else False))
                .all())
    existing_map = {(a.session_id, a.student_id): a for a in existing}

    created, updated = 0, 0
    for sid in student_ids:
        status = (request.form.get(f"status_{sid}", "PRESENT") or "PRESENT").strip().upper()
        note = (request.form.get(f"note_{sid}", "") or "").strip() or None

        key = (s.id, sid)
        if key in existing_map:
            a = existing_map[key]
            if a.status != status or (a.note or "") != (note or ""):
                a.status = status
                a.note = note
                updated += 1
        else:
            db.session.add(Attendance(session_id=s.id, student_id=sid, status=status, note=note))
            created += 1

    db.session.commit()
    flash(f"حضور و غیاب ذخیره شد. (جدید: {created}، به‌روزشده: {updated})", "success")
    return redirect(url_for("attendance.session_view", course_id=course.id, session_id=s.id))


# --- API سبک برای آمار یک جلسه (در صورت نیاز UI) ---
@bp.get("/<int:course_id>/session/<int:session_id>/stats.json")
@login_required
def session_stats_json(course_id, session_id):
    course = _get_course_or_404(course_id)
    _ = CourseSession.query.filter_by(id=session_id, course_id=course.id).first_or_404()
    return jsonify(_session_stats(session_id))

# ...

@bp.get("/")
@login_required
def index():
    """
    لاندر حضور و غیاب: لیست دوره‌ها با لینک ورود به تاریخچه و جلسه امروز (اگر وجود داشته باشد).
    """
    # می‌تونی فیلتر یا صفحه‌بندی هم بذاری؛ فعلاً ساده:
    q = (request.args.get("q") or "").strip()
    query = Course.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Course.title.ilike(like), Course.mentor_name.ilike(like)))

    courses = query.order_by(Course.id.desc()).limit(50).all()

    # برای هر دوره، جلسه امروز (اگر باشد) را پیدا کنیم تا لینک سریع بدهیم
    today = _today_local()
    today_session_id = {}
    if courses:
        sessions = (
            CourseSession.query
            .filter(CourseSession.course_id.in_([c.id for c in courses]),
                    CourseSession.session_date == today)
            .all()
        )
        by_course = {}
        for s in sessions:
            by_course.setdefault(s.course_id, []).append(s)
        for c in courses:
            sid = (by_course.get(c.id) or [None])[0]
            today_session_id[c.id] = sid.id if sid else None

    return render_template("attendance/index.html", courses=courses, today_session_id=today_session_id)
