from __future__ import annotations

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func, or_
from datetime import date

from app.extensions import db
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.core import Student
from app.models.mentor import Mentor
from app.models.payment import Payment  # kind: tuition/mentor_share, status: paid/pending/unpaid

bp = Blueprint("finance", __name__, url_prefix="/finance")

# تلاش اختیاری برای دارایی/هزینه (اگر مدل‌ها ایجاد نشده باشند، gracefully عبور می‌کنیم)
try:
    from app.models.asset import Asset
except Exception:  # noqa
    Asset = None  # type: ignore
try:
    from app.models.expense import Expense
except Exception:  # noqa
    Expense = None  # type: ignore


# ---------------- Helpers ----------------
def _sum_paid_tuition(course_id: int | None = None, student_id: int | None = None) -> float:
    q = db.session.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
        Payment.kind == "tuition",
        Payment.status == "paid",
    )
    if course_id is not None:
        q = q.filter(Payment.course_id == course_id)
    if student_id is not None:
        q = q.filter(Payment.student_id == student_id)
    return float(q.scalar() or 0.0)

def _sum_paid_mentor(course_id: int | None = None, mentor_id: int | None = None) -> float:
    q = db.session.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
        Payment.kind == "mentor_share",
        Payment.status == "paid",
    )
    if course_id is not None:
        q = q.filter(Payment.course_id == course_id)
    if mentor_id is not None:
        q = q.filter(Payment.mentor_id == mentor_id)
    return float(q.scalar() or 0.0)

def _course_face_fee(course: Course) -> float:
    per = float(getattr(course, "tuition_per_student", 0) or 0)
    active_count = db.session.query(func.count(Enrollment.id)).filter(
        Enrollment.course_id == course.id,
        Enrollment.status == "ACTIVE",
    ).scalar() or 0
    return per * active_count


# =========================
# داشبورد تب‌دار (یک صفحه)
# =========================
@bp.get("/")
@login_required
def dashboard():
    # ---- KPIs بالا
    total_face = 0.0
    for c in Course.query.all():
        total_face += _course_face_fee(c)

    total_received = float(
        db.session.query(func.coalesce(func.sum(Payment.amount), 0.0))
        .filter(Payment.kind == "tuition", Payment.status == "paid")
        .scalar()
        or 0.0
    )
    total_receivables = max(total_face - total_received, 0.0)

    today = date.today()
    overdue_count = int(
        db.session.query(func.count(Payment.id))
        .filter(
            Payment.kind == "tuition",
            Payment.status != "paid",
            Payment.due_date.isnot(None),
            Payment.due_date < today,
        )
        .scalar()
        or 0
    )

    rows = (
        db.session.query(
            func.strftime("%Y-%m", Payment.created_at).label("ym"),
            func.coalesce(func.sum(Payment.amount), 0.0).label("amt"),
        )
        .filter(Payment.kind == "tuition", Payment.status == "paid")
        .group_by("ym")
        .order_by("ym")
        .all()
    )
    monthly = [{"ym": ym or "...", "amount": float(amt or 0.0)} for ym, amt in rows]

    # ---- تب مطالبات دانشجو (receivables)
    rec_items = []
    base = (
        db.session.query(Enrollment, Course, Student)
        .join(Course, Course.id == Enrollment.course_id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(Enrollment.status == "ACTIVE")
    ).order_by(Course.id.desc()).all()

    for en, co, st in base:
        face = float(getattr(co, "tuition_per_student", 0) or 0.0)
        received = _sum_paid_tuition(course_id=co.id, student_id=st.id)
        remain = max(face - received, 0.0)
        rec_items.append(
            {
                "en_id": en.id,
                "student_name": (f"{st.first_name or ''} {st.last_name or ''}".strip() or f"دانشجو #{st.id}"),
                "student_id": st.id,
                "course_title": co.title,
                "course_id": co.id,
                "fee": int(face),
                "received": int(received),
                "remain": int(remain),
            }
        )

    # ---- تب دوره‌ها (courses report)
    courses_data = []
    for c in Course.query.order_by(Course.id.desc()).all():
        face_total = _course_face_fee(c)
        received = _sum_paid_tuition(course_id=c.id)
        remain = max(face_total - received, 0.0)
        mentor_share = float(c.mentor_share_percent or 0.0) * received / 100.0
        paid_to_mentor = _sum_paid_mentor(course_id=c.id, mentor_id=c.mentor_id)
        mentor_due = max(mentor_share - paid_to_mentor, 0.0)
        active_cnt = (
            db.session.query(func.count(Enrollment.id))
            .filter(Enrollment.course_id == c.id, Enrollment.status == "ACTIVE")
            .scalar()
            or 0
        )
        courses_data.append(
            {
                "course": c,
                "students": int(active_cnt),
                "face": int(face_total),
                "received": int(received),
                "remain": int(remain),
                "mentor_share": int(mentor_share),
                "mentor_paid": int(paid_to_mentor),
                "mentor_due": int(mentor_due),
            }
        )

    # ---- تب منتورها (mentors report)
    mentor_rows = []
    for m in Mentor.query.order_by(Mentor.id.desc()).all():
        mentor_courses = Course.query.filter(Course.mentor_id == m.id).all()
        total_received_m = 0.0
        total_share_m = 0.0
        for c in mentor_courses:
            rc = _sum_paid_tuition(course_id=c.id)
            total_received_m += rc
            total_share_m += rc * float(c.mentor_share_percent or 0.0) / 100.0
        paid_m = _sum_paid_mentor(mentor_id=m.id)
        due_m = max(total_share_m - paid_m, 0.0)
        mentor_rows.append(
            {
                "mentor": m,
                "courses": len(mentor_courses),
                "received": int(total_received_m),
                "share": int(total_share_m),
                "paid": int(paid_m),
                "due": int(due_m),
            }
        )

    # ---- تب اقساط (از Payment)
    inst_items = []
    inst_q = Payment.query.filter(
        Payment.kind == "tuition",
        Payment.status != "paid",
        Payment.due_date.isnot(None),
    ).order_by(Payment.due_date.asc(), Payment.created_at.asc()).all()
    for p in inst_q:
        inst_items.append(
            {
                "course": p.course,
                "title": p.title or f"قسط #{p.id}",
                "due": p.due_date.isoformat() if p.due_date else "-",
                "amount": int(p.amount or 0),
                "overdue": (p.due_date is not None) and (p.due_date < today),
            }
        )

    # ---- تب دارایی‌ها (اختیاری)
    assets = []
    assets_total_value = 0
    if Asset:
        assets = Asset.query.order_by(getattr(Asset, "id").desc()).all()
        try:
            assets_total_value = int(sum(a.current_value() for a in assets))
        except Exception:
            assets_total_value = int(sum(int(getattr(a, "cost", 0) or 0) for a in assets))

    # ---- تب هزینه‌ها (اختیاری)
    expenses = []
    expenses_total = 0
    if Expense:
        expenses = Expense.query.order_by(getattr(Expense, "paid_at").desc()).all()
        expenses_total = int(sum(int(getattr(e, "amount", 0) or 0) for e in expenses))

    return render_template(
        "finance/dashboard.html",
        # KPI
        kpis={
            "total_face": int(total_face),
            "total_received": int(total_received),
            "total_receivables": int(total_receivables),
            "overdue_count": int(overdue_count),
        },
        monthly=monthly,
        # tabs data
        receivables=rec_items,
        courses=courses_data,
        mentors=mentor_rows,
        installments=inst_items,
        assets=assets,
        assets_total=assets_total_value,
        expenses=expenses,
        expenses_total=expenses_total,
        AssetModelPresent=bool(Asset),
        ExpenseModelPresent=bool(Expense),
    )


# ============ (اختیاری) صفحات جداگانه قبلی را نگه می‌داریم تا لینک‌های قدیمی هم کار کنند ============
@bp.get("/receivables")
@login_required
def receivables():
    q = (request.args.get("q") or "").strip()
    course_id = request.args.get("course_id", type=int)
    mentor_id = request.args.get("mentor_id", type=int)

    base = (
        db.session.query(Enrollment, Course, Student)
        .join(Course, Course.id == Enrollment.course_id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(Enrollment.status == "ACTIVE")
    )

    if course_id:
        base = base.filter(Enrollment.course_id == course_id)
    if mentor_id:
        base = base.filter(Course.mentor_id == mentor_id)
    if q:
        like = f"%{q}%"
        base = base.filter(
            or_(Student.first_name.ilike(like), Student.last_name.ilike(like), Student.phone.ilike(like))
        )

    rows = base.order_by(Course.id.desc()).all()

    items = []
    for en, co, st in rows:
        face = float(getattr(co, "tuition_per_student", 0) or 0.0)
        received = _sum_paid_tuition(course_id=co.id, student_id=st.id)
        remain = max(face - received, 0.0)
        items.append(
            {
                "en_id": en.id,
                "student_name": (f"{st.first_name or ''} {st.last_name or ''}".strip() or f"دانشجو #{st.id}"),
                "student_id": st.id,
                "course_title": co.title,
                "course_id": co.id,
                "fee": int(face),
                "received": int(received),
                "remain": int(remain),
            }
        )

    courses = Course.query.order_by(Course.title.asc()).all()
    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    return render_template("finance/receivables.html", items=items, courses=courses, mentors=mentors)


@bp.get("/courses")
@login_required
def courses_report():
    q = (request.args.get("q") or "").strip()
    mentor_id = request.args.get("mentor_id", type=int)

    base = Course.query
    if q:
        base = base.filter(Course.title.ilike(f"%{q}%"))
    if mentor_id:
        base = base.filter(Course.mentor_id == mentor_id)

    data = []
    for c in base.order_by(Course.id.desc()).all():
        face_total = _course_face_fee(c)
        received = _sum_paid_tuition(course_id=c.id)
        remain = max(face_total - received, 0.0)
        mentor_share = float(c.mentor_share_percent or 0.0) * received / 100.0
        paid_to_mentor = _sum_paid_mentor(course_id=c.id, mentor_id=c.mentor_id)
        mentor_due = max(mentor_share - paid_to_mentor, 0.0)
        active_cnt = (
            db.session.query(func.count(Enrollment.id))
            .filter(Enrollment.course_id == c.id, Enrollment.status == "ACTIVE")
            .scalar()
            or 0
        )
        data.append(
            {
                "course": c,
                "students": int(active_cnt),
                "face": int(face_total),
                "received": int(received),
                "remain": int(remain),
                "mentor_share": int(mentor_share),
                "mentor_paid": int(paid_to_mentor),
                "mentor_due": int(mentor_due),
            }
        )

    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    return render_template("finance/courses.html", items=data, mentors=mentors)


@bp.get("/mentors")
@login_required
def mentors_report():
    rows = []
    for m in Mentor.query.order_by(Mentor.id.desc()).all():
        mentor_courses = Course.query.filter(Course.mentor_id == m.id).all()
        total_received = 0.0
        total_share = 0.0
        for c in mentor_courses:
            rc = _sum_paid_tuition(course_id=c.id)
            total_received += rc
            total_share += rc * float(c.mentor_share_percent or 0.0) / 100.0
        paid = _sum_paid_mentor(mentor_id=m.id)
        due = max(total_share - paid, 0.0)
        rows.append(
            {
                "mentor": m,
                "courses": len(mentor_courses),
                "received": int(total_received),
                "share": int(total_share),
                "paid": int(paid),
                "due": int(due),
            }
        )
    return render_template("finance/mentors.html", items=rows)


@bp.get("/installments")
@login_required
def installments():
    today = date.today()
    rows = (
        Payment.query.filter(
            Payment.kind == "tuition",
            Payment.status != "paid",
            Payment.due_date.isnot(None),
        )
        .order_by(Payment.due_date.asc(), Payment.created_at.asc())
        .all()
    )
    items = []
    for p in rows:
        items.append(
            {
                "course": p.course,
                "title": p.title or f"قسط #{p.id}",
                "due": p.due_date.isoformat() if p.due_date else "-",
                "amount": int(p.amount or 0),
                "overdue": (p.due_date is not None) and (p.due_date < today),
            }
        )
    all_courses = Course.query.order_by(Course.title.asc()).all()
    return render_template("finance/installments.html", items=items, courses=all_courses)
