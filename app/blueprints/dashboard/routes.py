# app/blueprints/dashboard/routes.py
from datetime import date
from flask import Blueprint, render_template
from flask_login import login_required,current_user
from sqlalchemy import func
from app.extensions import db
from app.models.payment import Payment
from app.models.course_session import CourseSession
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.core import Student
from app.models.mentor import Mentor
from flask_login import current_user
from sqlalchemy import or_

bp = Blueprint("dashboard", __name__, url_prefix="/")
#----------Helpers------------
def _get_today_sessions_for_student(user):
    """جلسات امروز برای دانشجویی که لاگین کرده."""
    try:
        today = date.today()
        # پیدا کردن student مرتبط با این یوزر
        student = Student.query.filter_by(user_id=user.id).first()
        if not student:
            return []

        # ثبت‌نام‌های فعال/درحال‌برگزاری
        enrollments = (
            Enrollment.query
            .filter(
                Enrollment.student_id == student.id,
                Enrollment.status.in_(("ACTIVE", "ONGOING"))
            )
            .all()
        )
        if not enrollments:
            return []

        course_ids = {en.course_id for en in enrollments if en.course_id}
        if not course_ids:
            return []

        # جلسات امروز این دوره‌ها
        sessions = (
            CourseSession.query
            .join(Course, Course.id == CourseSession.course_id)
            .filter(
                CourseSession.course_id.in_(course_ids),
                CourseSession.session_date == today,
            )
            .order_by(CourseSession.date.asc())
            .all()
        )
        return sessions
    except Exception:
        # اگر هر مشکلی بود، سکشن رو خفه‌خون می‌کنیم نه اینکه داشبورد بترکه
        return []
def _get_today_sessions_for_mentor(user):
    """جلسات امروز برای منتوری که لاگین کرده."""
    try:
        today = date.today()
        mentor = Mentor.query.filter_by(user_id=user.id).first()
        if not mentor:
            return []

        # جلساتی که mentor_id مستقیم خود منتوره
        q = CourseSession.query.filter(
            CourseSession.session_date == today,
            or_(
                CourseSession.mentor_id == mentor.id,
                # اگر mentor_id روی جلسه خالی بود، ولی mentor روی خود دوره ست شده
                CourseSession.mentor_id.is_(None),
            ),
        )

        # فیلتر تکمیلی: اگر mentor_id تهی است، فقط جلسات دوره‌هایی که mentor آن‌هاست
        sessions = []
        for s in q.order_by(CourseSession.date.asc()).all():
            if s.mentor_id == mentor.id:
                sessions.append(s)
            else:
                # اگر mentor_id خالی است، چک کنیم mentor خود دوره
                c = getattr(s, "course", None)
                if c is not None and getattr(c, "mentor_id", None) == mentor.id:
                    sessions.append(s)

        return sessions
    except Exception:
        return []
#----------API----------------
@bp.get("/")
@login_required
def index():
    print(f"User Role: {current_user.role}")
    ctx = {}

    role = (getattr(current_user, "role", "") or "").lower()

    today_sessions_student = []
    today_sessions_mentor = []

    if role == "student":
        today_sessions_student = _get_today_sessions_for_student(current_user)
    elif role in ("mentor", "MENTOR"):  # اگر جایی با حروف بزرگ ذخیره شده
        today_sessions_mentor = _get_today_sessions_for_mentor(current_user)
    # --- محاسبات KPI (نمونه؛ جایگزین با منطق خودتان اگر قبلاً نوشته‌اید)
    total_face = 0
    total_received = db.session.query(
        func.coalesce(func.sum(Payment.amount), 0.0)
    ).filter(Payment.kind == "tuition", Payment.status == "paid").scalar() or 0.0
    total_receivables = max(total_face - total_received, 0.0)
    overdue_count = 0  # اگر دارید از installments می‌خوانید این را محاسبه کنید

    # روند ماهانه دریافت‌ها (cash-basis)
    monthly_rows = (
        db.session.query(
            func.strftime("%Y-%m", Payment.paid_at).label("ym"),
            func.coalesce(func.sum(Payment.amount), 0.0),
        )
        .filter(Payment.kind == "tuition", Payment.status == "paid")
        .group_by("ym").order_by("ym")
        .all()
    )
    monthly = [{"ym": ym or "...", "amount": float(s or 0)} for ym, s in monthly_rows]
    monthly_max = max((m["amount"] for m in monthly), default=1.0)

    # ---- آبجکت‌های خروجی برای سازگاری قالب
    kpis = {
        "total_face": int(total_face),
        "total_received": int(total_received),
        "total_receivables": int(total_receivables),
        "overdue_count": int(overdue_count),
    }
    data = {
        "kpis": kpis,              # ← تا {{ data.kpis.* }} کار کند
        "monthly": monthly,        # ← اگر قالب از data.monthly استفاده کند
        "monthly_max": monthly_max,
    }

    return render_template(
        "dashboard/index.html",
        # دو مسیر موازی برای سازگاری با همه‌ی ارجاعات قالب
        data=data,
        kpis=kpis,
        monthly=monthly,
        monthly_max=monthly_max,
        today_sessions_student=today_sessions_student,
        today_sessions_mentor=today_sessions_mentor,
        **ctx,
    )
