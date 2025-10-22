# app/blueprints/finance/routes.py
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
    # شهریه اسمی دوره = tuition_per_student × تعداد Enrollmentهای ACTIVE
    per = float(course.tuition_per_student or 0)
    active_count = db.session.query(func.count(Enrollment.id)).filter(
        Enrollment.course_id == course.id,
        Enrollment.status == "ACTIVE",
    ).scalar() or 0
    return per * active_count

# ============ Dashboard ============
@bp.get("/")
@login_required
def dashboard():
    # 1) شهریه اسمی کل
    total_face = 0.0
    for c in Course.query.all():
        total_face += _course_face_fee(c)

    # 2) دریافتی نقدی کل
    total_received = float(
        db.session.query(func.coalesce(func.sum(Payment.amount), 0.0))
        .filter(Payment.kind == "tuition", Payment.status == "paid")
        .scalar()
        or 0.0
    )

    # 3) مطالبات باز
    total_receivables = max(total_face - total_received, 0.0)

    # 4) اقساط سررسیدگذشته
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

    # 5) درآمد ماهانه
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

    # ✅ بازگشت با تمام داده‌ها
    return render_template(
        "finance/dashboard.html",
        kpis={
            "total_face": int(total_face),
            "total_received": int(total_received),
            "total_receivables": int(total_receivables),
            "overdue_count": overdue_count,
        },
        monthly=monthly,
    )

# ============ Receivables by student ============
@bp.get("/receivables")
@login_required
def receivables():
    q = (request.args.get("q") or "").strip()
    course_id = request.args.get("course_id", type=int)
    mentor_id = request.args.get("mentor_id", type=int)
    status = request.args.get("status")  # open/closed

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
        face = float(co.tuition_per_student or 0.0)
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

    if status == "open":
        items = [x for x in items if x["remain"] > 0]
    elif status == "closed":
        items = [x for x in items if x["remain"] <= 0]

    courses = Course.query.order_by(Course.title.asc()).all()
    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    return render_template("finance/receivables.html", items=items, courses=courses, mentors=mentors)

# ============ Course revenue ============
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

# ============ Mentor settlements ============
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

# ============ Installments (از جدول payments) ============
@bp.get("/installments")
@login_required
def installments():
    """
    گزارش اقساط باز/سررسیدگذشته بر اساس رکوردهای Payment:
      - kind='tuition'
      - status!='paid'
      - due_date != NULL
    """
    q = (request.args.get("q") or "").strip()
    course_id = request.args.get("course_id", type=int)

    base = Payment.query.filter(
        Payment.kind == "tuition",
        Payment.status != "paid",
        Payment.due_date.isnot(None),
    )
    if course_id:
        base = base.filter(Payment.course_id == course_id)
    if q:
        base = base.filter(Payment.title.ilike(f"%{q}%"))

    today = date.today()
    rows = (
        base.order_by(Payment.due_date.asc(), Payment.created_at.asc())
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
