# app/blueprints/finance/routes.py
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required
from sqlalchemy import func, or_

from app.extensions import db
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.core import Student
from app.models.mentor import Mentor
from app.models.payment import Payment  # kind: tuition/mentor_share , status: paid/pending/unpaid
from app.models.mentor_payment import MentorPayment  # پرداختی‌های منتورها

bp = Blueprint("finance", __name__, url_prefix="/finance")

# مدل‌های اختیاری
try:
    from app.models.asset import Asset  # type: ignore
except Exception:  # noqa
    Asset = None  # type: ignore
try:
    from app.models.expense import Expense  # type: ignore
except Exception:  # noqa
    Expense = None  # type: ignore


# ---------------- Helpers ----------------
def _mentor_pct(course: Course) -> float:
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


def _safe_num(val, default=0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def _is_inflow(p: Payment) -> bool:
    status = (getattr(p, "status", "") or "paid").lower()
    kind = (getattr(p, "kind", "") or "tuition").lower()
    if status in {"cancelled", "canceled", "void"}:
        return False
    if kind in {"mentor_share", "expense", "refund"}:
        return False
    return True


def _sum_paid_tuition(
    course_id: int | None = None,
    student_id: int | None = None,
    enrollment_id: int | None = None,
) -> float:
    amount_col = getattr(Payment, "amount")
    status_ok = func.coalesce(func.lower(getattr(Payment, "status")), "paid") == "paid"
    kind_col = func.lower(getattr(Payment, "kind"))
    not_excluded_kind = ~kind_col.in_(("mentor_share", "expense", "refund"))

    q = db.session.query(func.coalesce(func.sum(amount_col), 0.0)).filter(
        amount_col > 0, status_ok, not_excluded_kind
    )

    if enrollment_id is not None and hasattr(Payment, "enrollment_id"):
        q = q.filter(Payment.enrollment_id == enrollment_id)
        return float(q.scalar() or 0.0)

    if student_id is not None and hasattr(Payment, "student_id"):
        q = q.filter(Payment.student_id == student_id)

    if course_id is not None and hasattr(Payment, "course_id"):
        q = q.filter((Payment.course_id == course_id) | (Payment.course_id.is_(None)))

    return float(q.scalar() or 0.0)


def _sum_paid_mentor(course_id: int | None = None, mentor_id: int | None = None) -> float:
    """
    جمع پرداخت‌های انجام‌شده به منتور:
    - منبع اصلی: MentorPayment(kind='EXPENSE')  [+ فیلتر course_id اگر ستونش وجود داشت]
    - fallback: Payment(kind='mentor_share' & status='paid')
    """
    total = 0.0
    try:
        q = db.session.query(func.coalesce(func.sum(MentorPayment.amount), 0.0)).filter(
            func.lower(MentorPayment.kind) == "expense"
        )
        if mentor_id is not None and hasattr(MentorPayment, "mentor_id"):
            q = q.filter(MentorPayment.mentor_id == mentor_id)
        if course_id is not None and hasattr(MentorPayment, "course_id"):
            q = q.filter(MentorPayment.course_id == course_id)
        total = float(q.scalar() or 0.0)
    except Exception:
        total = 0.0

    # اگر صفر بود و مدل MentorPayment به هر دلیلی جواب نداد → fallback
    if total <= 0.0:
        q2 = db.session.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            func.lower(Payment.kind) == "mentor_share",
            func.coalesce(func.lower(Payment.status), "paid") == "paid",
        )
        if mentor_id is not None and hasattr(Payment, "mentor_id"):
            q2 = q2.filter(Payment.mentor_id == mentor_id)
        if course_id is not None and hasattr(Payment, "course_id"):
            q2 = q2.filter(Payment.course_id == course_id)
        total = float(q2.scalar() or 0.0)

    return total


def _active_students_count(course_id: int) -> int:
    return int(
        db.session.query(func.count(Enrollment.id))
        .filter(Enrollment.course_id == course_id, Enrollment.status == "ACTIVE")
        .scalar()
        or 0
    )


def _course_face_fee(course: Course) -> float:
    per = float(getattr(course, "tuition_per_student", 0) or 0)
    return per * _active_students_count(course.id)


def _norm_text(x):
    try:
        return (x or "").strip().lower()
    except Exception:
        return ""


def _course_belongs_to_mentor(c: Course, m: Mentor) -> bool:
    """
    تشخیص وابستگی دوره به منتور با چندین راه:
    1) course.mentor_id == mentor.id  (با تحمل int/str)
    2) course.mentor.id == mentor.id
    3) course.mentor_name ≈ mentor.full_name/first+last (اگر چنین فیلدی باشد)
    """
    mid1 = getattr(c, "mentor_id", None)
    if mid1 is not None:
        try:
            if int(mid1) == int(m.id):
                return True
        except Exception:
            # str-compare fallback
            if str(mid1) == str(m.id):
                return True

    mid2 = getattr(getattr(c, "mentor", None), "id", None)
    if mid2 is not None:
        try:
            if int(mid2) == int(m.id):
                return True
        except Exception:
            if str(mid2) == str(m.id):
                return True

    # نام منتور (اختیاری)
    c_name = _norm_text(getattr(c, "mentor_name", None))
    if c_name:
        m_full = _norm_text(getattr(m, "full_name", None))
        m_pair = _norm_text(f"{getattr(m,'first_name', '')} {getattr(m,'last_name','')}")
        if c_name and (c_name == m_full or c_name == m_pair):
            return True

    return False


# =========================
# داشبورد تب‌محور (یک صفحه)
# =========================
@bp.get("/")
@login_required
def dashboard():
    today = date.today()
    start_month = date(today.year, today.month, 1)
    next_month = (start_month.replace(day=28) + timedelta(days=4)).replace(day=1)

    enrollments = Enrollment.query.all()
    payments = Payment.query.all()

    # --- KPI: شهریه اسمی کل ---
    total_face = 0.0
    for c in Course.query.all():
        total_face += _course_face_fee(c)

    # --- دریافتی‌ها + MTD + سری 12 ماه ---
    total_received = 0.0
    mtd_received = 0.0
    receipts_12m: dict[tuple[int, int], float] = defaultdict(float)

    for p in payments:
        amt = _safe_num(getattr(p, "amount", None), 0.0)
        if not _is_inflow(p) or amt <= 0:
            continue
        paid_at = getattr(p, "paid_at", None) or getattr(p, "created_at", None)
        if isinstance(paid_at, date) and not isinstance(paid_at, datetime):
            paid_dt = datetime.combine(paid_at, datetime.min.time())
        else:
            paid_dt = paid_at or datetime.combine(today, datetime.min.time())
        total_received += amt
        if start_month <= paid_dt.date() < next_month:
            mtd_received += amt
        receipts_12m[(paid_dt.year, paid_dt.month)] += amt

    # --- هزینه‌های ماه جاری (اختیاری) ---
    mtd_expense = 0.0
    expenses_total = 0
    expense_mtd_by_cat: dict[str, float] = defaultdict(float)
    expenses = []
    if Expense:
        q = Expense.query
        order_cols = []
        if hasattr(Expense, "paid_at"):
            order_cols.append(getattr(Expense, "paid_at").desc().nullslast())
        if hasattr(Expense, "created_at"):
            order_cols.append(getattr(Expense, "created_at").desc().nullslast())
        if hasattr(Expense, "id"):
            order_cols.append(getattr(Expense, "id").desc())
        if order_cols:
            q = q.order_by(*order_cols)
        expenses = q.all()
        for ex in expenses:
            ex_amt = _safe_num(
                getattr(ex, "amount", None)
                or getattr(ex, "amount_total", None)
                or getattr(ex, "amount_net", None),
                0.0,
            )
            expenses_total += int(ex_amt)
            paid_at = getattr(ex, "paid_at", None) or getattr(ex, "created_at", None)
            cat = getattr(ex, "category", None) or "سایر"
            paid_date = paid_at.date() if isinstance(paid_at, datetime) else paid_at
            if paid_date and (start_month <= paid_date < next_month):
                mtd_expense += ex_amt
                expense_mtd_by_cat[cat] += ex_amt

    # --- معوقات/اقساط باز و آینده ---
    total_receivables = max(total_face - total_received, 0.0)
    overdue_count = 0
    overdue_amount = 0.0
    upcoming_7: list[Payment] = []
    aging_buckets = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}

    for p in payments:
        amt = _safe_num(getattr(p, "amount", None), 0.0)
        if amt <= 0:
            continue
        status = (getattr(p, "status", "") or "").lower()
        if status in {"paid", "settled"}:
            continue
        due_date = getattr(p, "due_date", None)
        if not due_date:
            continue
        delay_days = (today - due_date).days
        if delay_days > 0:
            overdue_count += 1
            overdue_amount += amt
            if delay_days <= 30:
                aging_buckets["0-30"] += amt
            elif delay_days <= 60:
                aging_buckets["31-60"] += amt
            elif delay_days <= 90:
                aging_buckets["61-90"] += amt
            else:
                aging_buckets["90+"] += amt
        else:
            ahead = (due_date - today).days
            if 0 <= ahead <= 7:
                upcoming_7.append(p)

    # --- دوره‌های پرفروش ماه جاری ---
    top_courses_mtd: dict[str, dict] = defaultdict(lambda: {"title": "—", "count": 0, "amount": 0.0})
    for p in payments:
        amt = _safe_num(getattr(p, "amount", None), 0.0)
        if amt <= 0:
            continue
        paid_at = getattr(p, "paid_at", None) or getattr(p, "created_at", None)
        paid_date = paid_at.date() if isinstance(ped_at := paid_at, datetime) else paid_at
        if not (paid_date and (start_month <= paid_date < next_month)):
            continue
        title = getattr(getattr(p, "course", None), "title", None)
        if not title:
            enr = getattr(p, "enrollment", None)
            if enr:
                title = getattr(getattr(enr, "course", None), "title", None)
        key = title or "—"
        top_courses_mtd[key]["title"] = key
        top_courses_mtd[key]["count"] += 1
        top_courses_mtd[key]["amount"] += amt
    top_courses_mtd_list = sorted(top_courses_mtd.values(), key=lambda x: x["amount"], reverse=True)[:10]

    # --- دارایی‌ها (اختیاری) ---
    assets = []
    assets_total = 0
    if Asset:
        q = Asset.query
        if hasattr(Asset, "in_service_date"):
            q = q.order_by(Asset.in_service_date.desc().nullslast(), Asset.id.desc())
        elif hasattr(Asset, "purchase_date"):
            q = q.order_by(Asset.purchase_date.desc().nullslast(), Asset.id.desc())
        else:
            q = q.order_by(Asset.id.desc())
        assets = q.all()
        try:
            assets_total = int(
                sum(
                    int(getattr(a, "current_value")() if callable(getattr(a, "current_value", None)) else (getattr(a, "cost", 0) or 0))
                    for a in assets
                )
            )
        except Exception:
            assets_total = int(sum(int(getattr(a, "cost", 0) or 0) for a in assets))

    # --- میانگین تأخیر وصول ---
    delays = []
    for p in payments:
        if (getattr(p, "status", "") or "").lower() in {"paid", "settled"}:
            continue
        due_date = getattr(p, "due_date", None)
        if not due_date:
            continue
        d = (today - due_date).days
        if d > 0:
            delays.append(d)
    avg_delay_days = round(sum(delays) / len(delays), 1) if delays else None

    # --- سری ۱۲ ماه اخیر (monthly) ---
    months, amounts, monthly = [], [], []
    cur = date(today.year, today.month, 1)
    last12 = []
    for _ in range(12):
        last12.append((cur.year, cur.month))
        cur = (cur.replace(day=1) - timedelta(days=1)).replace(day=1)
    last12.reverse()
    for (y, m) in last12:
        ym_str = f"{y}-{str(m).zfill(2)}"
        val = round(receipts_12m.get((y, m), 0.0), 2)
        months.append(ym_str)
        amounts.append(val)
        monthly.append({"ym": ym_str, "amount": int(val)})

    # === تب «مطالبات دانشجو» ===
    rec_items = []
    base = (
        db.session.query(Enrollment, Course, Student)
        .join(Course, Course.id == Enrollment.course_id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(Enrollment.status == "ACTIVE")
        .order_by(Course.id.desc())
        .all()
    )
    for en, co, st in base:
        face = float(getattr(co, "tuition_per_student", 0) or 0.0)
        received = _sum_paid_tuition(enrollment_id=en.id, course_id=co.id, student_id=st.id)
        remain = max(face - received, 0.0)
        rec_items.append(
            dict(
                en_id=en.id,
                student_name=(f"{st.first_name or ''} {st.last_name or ''}".strip() or f"دانشجو #{st.id}"),
                student_id=st.id,
                course_title=co.title,
                course_id=co.id,
                fee=int(face),
                received=int(received),
                remain=int(remain),
            )
        )

    # === تب «دوره‌ها» ===
    course_rows = []
    # پیش‌محاسبه‌ی مجموع سهم/پرداخت منتور برای «پخش» روی دوره‌ها (اگر لازم بود)
    mentor_share_totals: dict[int, float] = {}
    mentor_paid_totals: dict[int, float] = {}
    for m in Mentor.query.all():
        total_face_share = 0.0
        for c in Course.query.all():
            if _course_belongs_to_mentor(c, m):
                total_face_share += _course_face_fee(c) * _mentor_pct(c)
        mentor_share_totals[m.id] = total_face_share
        mentor_paid_totals[m.id] = _sum_paid_mentor(mentor_id=m.id)

    for c in Course.query.order_by(Course.id.desc()).all():
        face_total   = _course_face_fee(c)
        received     = _sum_paid_tuition(course_id=c.id)
        remain       = max(face_total - received, 0.0)
        pct          = _mentor_pct(c)
        mentor_share = face_total * pct  # مبنا: کل هزینه دوره
        m_ref = getattr(c, "mentor_id", None)
        if m_ref is None:
            m_ref = getattr(getattr(c, "mentor", None), "id", None)
        m_id = int(m_ref) if m_ref is not None else 0

        mentor_paid_total  = mentor_paid_totals.get(m_id, 0.0)
        mentor_share_total = mentor_share_totals.get(m_id, 0.0) or 0.0
        mentor_paid_for_course = mentor_paid_total * (mentor_share / mentor_share_total) if mentor_share_total > 0 else 0.0
        mentor_due = max(mentor_share - mentor_paid_for_course, 0.0)

        course_rows.append(dict(
            course=c,
            students=_active_students_count(c.id),
            face=int(face_total),
            received=int(received),
            remain=int(remain),
            mentor_share=int(mentor_share),
            mentor_paid=int(mentor_paid_for_course),
            mentor_due=int(mentor_due),
        ))

    # === تب «منتورها» ===
    mentor_rows = []
    all_courses = Course.query.all()
    for m in Mentor.query.order_by(Mentor.id.desc()).all():
        mentor_courses = [c for c in all_courses if _course_belongs_to_mentor(c, m)]

        total_face_m = 0.0
        total_share_m = 0.0
        total_received_m = 0.0

        for c in mentor_courses:
            face_total = _course_face_fee(c)
            total_face_m += face_total
            total_share_m += face_total * _mentor_pct(c)
            total_received_m += _sum_paid_tuition(course_id=c.id)

        paid = _sum_paid_mentor(mentor_id=m.id)
        due  = max(total_share_m - paid, 0.0)

        mentor_rows.append(dict(
            mentor=m,
            courses=len(mentor_courses),
            received=int(total_received_m),
            share=int(total_share_m),
            paid=int(paid),
            due=int(due),
        ))

    # === تب «اقساط» ===
    inst_rows = []
    inst_base = Payment.query.filter(
        func.lower(Payment.kind) == "tuition",
        func.lower(Payment.status) != "paid",
        Payment.due_date.isnot(None),
    ).order_by(Payment.due_date.asc(), Payment.created_at.asc()).all()
    for p in inst_base:
        inst_rows.append(
            dict(
                course=p.course,
                title=p.title or f"قسط #{p.id}",
                due=p.due_date.isoformat() if p.due_date else "-",
                amount=int(p.amount or 0),
                overdue=(p.due_date is not None) and (p.due_date < today),
            )
        )

    # --- KPI های بالا ---
    kpis = dict(
        total_face=int(total_face),
        total_received=int(total_received),
        total_receivables=int(total_receivables),
        overdue_count=int(overdue_count),
        overdue_amount=int(overdue_amount),
        mtd_received=int(mtd_received),
        mtd_expense=int(mtd_expense),
        assets_value=int(assets_total),
        avg_delay_days=avg_delay_days,
        aging=aging_buckets,
    )

    return render_template(
        "finance/dashboard.html",
        kpis=kpis,
        monthly=monthly,
        receivables=rec_items,
        courses=course_rows,
        mentors=mentor_rows,
        installments=inst_rows,
        AssetModelPresent=bool(Asset),
        assets=assets,
        assets_total=int(assets_total),
        ExpenseModelPresent=bool(Expense),
        expenses=expenses,
        expenses_total=int(expenses_total),
        months=months,
        amounts=amounts,
        start_month=start_month,
        today=today,
        top_courses_mtd=top_courses_mtd_list,
        expense_mtd_by_cat=dict(expense_mtd_by_cat),
        upcoming_7=upcoming_7[:10],
    )


# ------------------------ صفحات تفکیکی ------------------------
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
        base = base.filter(or_(Student.first_name.ilike(like), Student.last_name.ilike(like), Student.phone.ilike(like)))

    rows = base.order_by(Course.id.desc()).all()
    items = []
    for en, co, st in rows:
        face = float(getattr(co, "tuition_per_student", 0) or 0.0)
        received = _sum_paid_tuition(enrollment_id=en.id, course_id=co.id, student_id=st.id)
        remain = max(face - received, 0.0)
        items.append(
            dict(
                en_id=en.id,
                student_name=(f"{st.first_name or ''} {st.last_name or ''}".strip() or f"دانشجو #{st.id}"),
                student_id=st.id,
                course_title=co.title,
                course_id=co.id,
                fee=int(face),
                received=int(received),
                remain=int(remain),
            )
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

        mentor_share = int(_course_face_fee(c) * _mentor_pct(c))  # مبنا: کل هزینه دوره
        # جمع پرداخت به منتور برای این دوره (اگر در MentorPayment ستون course_id باشد؛ وگرنه نسبتاً توزیع می‌شود)
        m_ref = getattr(c, "mentor_id", None)
        if m_ref is None:
            m_ref = getattr(getattr(c, "mentor", None), "id", None)
        paid_to_mentor = _sum_paid_mentor(course_id=c.id, mentor_id=(int(m_ref) if m_ref is not None else None))
        mentor_due = max(mentor_share - int(paid_to_mentor), 0)

        data.append(
            dict(
                course=c,
                students=_active_students_count(c.id),
                face=int(face_total),
                received=int(received),
                remain=int(remain),
                mentor_share=int(mentor_share),
                mentor_paid=int(paid_to_mentor),
                mentor_due=int(mentor_due),
            )
        )

    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    return render_template("finance/courses.html", items=data, mentors=mentors)


@bp.get("/mentors")
@login_required
def mentors_report():
    rows = []
    all_courses = Course.query.all()

    for m in Mentor.query.order_by(Mentor.id.desc()).all():
        mentor_courses = [c for c in all_courses if _course_belongs_to_mentor(c, m)]

        total_face = 0.0
        total_share = 0.0
        total_received = 0.0

        for c in mentor_courses:
            face_total = _course_face_fee(c)
            total_face += face_total
            total_share += face_total * _mentor_pct(c)
            total_received += _sum_paid_tuition(course_id=c.id)

        paid = _sum_paid_mentor(mentor_id=m.id)
        due  = max(total_share - paid, 0.0)

        rows.append({
            "mentor": m,
            "courses": len(mentor_courses),
            "received": int(total_received),
            "share": int(total_share),
            "paid": int(paid),
            "due": int(due),
        })

    return render_template("finance/mentors.html", items=rows)


@bp.get("/installments")
@login_required
def installments():
    today = date.today()
    rows = (
        Payment.query.filter(
            func.lower(Payment.kind) == "tuition",
            func.lower(Payment.status) != "paid",
            Payment.due_date.isnot(None),
        )
        .order_by(Payment.due_date.asc(), Payment.created_at.asc())
        .all()
    )
    items = []
    for p in rows:
        items.append(
            dict(
                course=p.course,
                title=p.title or f"قسط #{p.id}",
                due=p.due_date.isoformat() if p.due_date else "-",
                amount=int(p.amount or 0),
                overdue=(p.due_date is not None) and (p.due_date < today),
            )
        )
    all_courses = Course.query.order_by(Course.title.asc()).all()
    return render_template("finance/installments.html", items=items, courses=all_courses)


# ------------------------ Expenses (costs) ------------------------
@bp.get("/expenses")
@login_required
def expenses_page():
    if not Expense:
        return render_template("finance/expenses.html", items=[], courses=Course.query.order_by(Course.title.asc()).all())

    courses = Course.query.order_by(Course.title.asc()).all()

    q = Expense.query
    order_cols = []
    if hasattr(Expense, "paid_at"):
        order_cols.append(getattr(Expense, "paid_at").desc().nullslast())
    if hasattr(Expense, "created_at"):
        order_cols.append(getattr(Expense, "created_at").desc().nullslast())
    if hasattr(Expense, "id"):
        order_cols.append(getattr(Expense, "id").desc())
    if order_cols:
        q = q.order_by(*order_cols)

    items = q.limit(100).all()
    return render_template("finance/expenses.html", items=items, courses=courses)


@bp.post("/expenses/new")
@login_required
def expenses_new():
    from app.models.expense import Expense as _Expense  # type: ignore

    title = (request.form.get("title") or "").strip()
    amount_net = request.form.get("amount_net", type=float) or 0.0
    vat_rate = request.form.get("vat_rate", type=float) or 0.0
    payment_method = (request.form.get("payment_method") or "CASH").upper().strip()
    status = (request.form.get("status") or "PAID").upper().strip()
    is_fixed = True if request.form.get("is_fixed") == "1" else False
    course_id = request.form.get("course_id", type=int)
    note = (request.form.get("note") or "").strip() or None

    vat_amount = amount_net * (vat_rate / 100.0)
    surcharge_percent = request.form.get("surcharge_percent", type=float) or 0.0
    surcharge_amount = amount_net * (surcharge_percent / 100.0)
    amount_total = amount_net + vat_amount + surcharge_amount

    paid_at = None
    paid_at_str = (request.form.get("paid_at") or "").strip()
    if paid_at_str:
        try:
            paid_at = datetime.strptime(paid_at_str, "%Y-%m-%d").date()
        except Exception:
            paid_at = None

    exp = _Expense()
    if hasattr(exp, "title"): exp.title = title
    if hasattr(exp, "amount_net"): exp.amount_net = amount_net
    if hasattr(exp, "vat_rate"): exp.vat_rate = vat_rate
    if hasattr(exp, "vat_amount"): exp.vat_amount = vat_amount
    if hasattr(exp, "surcharge_percent"): exp.surcharge_percent = surcharge_percent
    if hasattr(exp, "surcharge_amount"): exp.surcharge_amount = surcharge_amount
    if hasattr(exp, "amount_total"): exp.amount_total = amount_total
    if hasattr(exp, "payment_method"): exp.payment_method = payment_method
    if hasattr(exp, "status"): exp.status = status
    if hasattr(exp, "is_fixed"): exp.is_fixed = is_fixed
    if hasattr(exp, "note"): exp.note = note
    if course_id and hasattr(exp, "course_id"): exp.course_id = course_id
    if paid_at and hasattr(exp, "paid_at"): exp.paid_at = paid_at

    category = (request.form.get("category") or "").strip().upper()
    if category and hasattr(exp, "category"):
        exp.category = category

    cheque_number = (request.form.get("cheque_number") or "").strip() or None
    bank_name = (request.form.get("bank_name") or "").strip() or None
    issuer_name = (request.form.get("issuer_name") or "").strip() or None
    issue_date = (request.form.get("issue_date") or "").strip() or None
    due_date = (request.form.get("due_date") or "").strip() or None
    if payment_method == "CHEQUE":
        if cheque_number and hasattr(exp, "cheque_number"): exp.cheque_number = cheque_number
        if bank_name and hasattr(exp, "bank_name"): exp.bank_name = bank_name
        if issuer_name and hasattr(exp, "issuer_name"): exp.issuer_name = issuer_name
        if issue_date and hasattr(exp, "issue_date"):
            try: exp.issue_date = datetime.strptime(issue_date, "%Y-%m-%d").date()
            except Exception: pass
        if due_date and hasattr(exp, "due_date"):
            try: exp.due_date = datetime.strptime(due_date, "%Y-%m-%d").date()
            except Exception: pass
        cheque_status = (request.form.get("cheque_status") or "").strip().upper()
        if cheque_status and hasattr(exp, "cheque_status"):
            exp.cheque_status = cheque_status

    db.session.add(exp)
    db.session.commit()
    return redirect(url_for("finance.expenses_page"))


# ------------------------ Assets (fixed assets) ------------------------
@bp.get("/assets")
@login_required
def assets_page():
    from app.models.asset import Asset as _Asset  # type: ignore
    items = (
        _Asset.query
        .order_by(_Asset.in_service_date.desc().nullslast(),
                  _Asset.purchase_date.desc().nullslast(),
                  _Asset.id.desc())
        .all()
    )
    courses = Course.query.order_by(Course.title.asc()).all()
    return render_template("finance/assets.html", items=items, courses=courses)


@bp.post("/assets/new")
@login_required
def assets_new():
    from app.models.asset import Asset as _Asset  # type: ignore

    a = _Asset()
    title = (request.form.get("title") or "").strip()
    if hasattr(a, "title"):
        a.title = title

    purchase_price = request.form.get("purchase_price", type=float) or 0.0
    if hasattr(a, "purchase_price"):
        a.purchase_price = purchase_price

    purchase_date = (request.form.get("purchase_date") or "").strip()
    if purchase_date and hasattr(a, "purchase_date"):
        try: a.purchase_date = datetime.strptime(purchase_date, "%Y-%m-%d").date()
        except Exception: pass

    in_service_date = (request.form.get("in_service_date") or "").strip()
    if in_service_date and hasattr(a, "in_service_date"):
        try: a.in_service_date = datetime.strptime(in_service_date, "%Y-%m-%d").date()
        except Exception: pass

    cid = request.form.get("course_id", type=int)
    if cid and hasattr(a, "course_id"):
        a.course_id = cid

    life = request.form.get("useful_life_months", type=int)
    if life and hasattr(a, "useful_life_months"):
        a.useful_life_months = life
    method = (request.form.get("depreciation_method") or "STRAIGHT_LINE").upper().strip()
    if hasattr(a, "depreciation_method"):
        a.depreciation_method = method

    category = (request.form.get("category") or "").strip()
    if category and hasattr(a, "category"):
        a.category = category
    residual_value = request.form.get("residual_value", type=float)
    if residual_value is not None and hasattr(a, "residual_value"):
        a.residual_value = residual_value

    db.session.add(a)
    db.session.commit()
    return redirect(url_for("finance.assets_page"))
