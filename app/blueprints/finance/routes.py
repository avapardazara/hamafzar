from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import func, or_
from app.extensions import db
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.core import Student
from app.models.mentor import Mentor
from app.models.payment import Payment  # kind: tuition/mentor_share , status: paid/pending/unpaid
from app.models.mentor_payment import MentorPayment  # پرداختی‌های منتورها
from app.models.installment_plan import InstallmentPlan
from app.models.installment import Installment
from app.models.asset import Asset


bp = Blueprint("finance", __name__, url_prefix="/finance")

# --------- مدل‌های اختیاری ---------
try:
    from app.models.expense import Expense  # type: ignore
except Exception:  # noqa
    Expense = None  # type: ignore


# ---------------- Helpers ----------------
def _inst_total(i):
    return int(
        (getattr(i, "amount_total", None)
         or (getattr(i, "amount_base", 0) or 0) + (getattr(i, "cheque_fee_amount", 0) or 0)) or 0
    )

def _is_installment_closed(i):
    return _inst_paid_amount(i) >= _inst_total(i)

def _inst_paid_amount(i):
    total = _inst_total(i)
    # اگر یکی از فیلدهای پرداخت پر باشد
    for attr in ("amount_paid", "paid_amount", "amount_received"):
        val = getattr(i, attr, None)
        if val is not None:
            try:
                v = int(val)
                return min(max(v, 0), total)
            except Exception:
                pass
    # اگر وضعیت قسط پرداخت‌شده باشد
    if (getattr(i, "status", "") or "").upper() in {"PAID", "SETTLED"}:
        return total
    return 0
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

def _is_paid(p: Payment) -> bool:
    return (getattr(p, "status", "") or "").lower() in {"paid", "settled"}

def _is_inflow_kind(kind_val: str) -> bool:
    k = (kind_val or "").lower()
    return k not in {"mentor_share", "expense", "refund"}

def _sum_paid_tuition(
    course_id: int | None = None,
    student_id: int | None = None,
    enrollment_id: int | None = None,
) -> float:
    """
    جمع دریافتی‌های شهریه که «واقعاً پرداخت شده‌اند» (status in paid/settled)
    و از جنس inflow هستند. NULL در kind به عنوان inflow محسوب می‌شود.
    """
    amount_col = getattr(Payment, "amount")

    # NULL وضعیت را 'paid' فرض نمی‌کنیم؛ فقط paid/settled را می‌گیریم
    status_ok = func.coalesce(func.lower(getattr(Payment, "status")), "pending").in_(("paid", "settled"))

    # اگر kind تهی باشد، آن را inflow حساب کن؛ فقط سه نوع زیر را حذف کن
    kind_col = func.lower(getattr(Payment, "kind"))
    inflow_condition = or_(
        kind_col.is_(None),  # NULL -> inflow
        ~kind_col.in_(("mentor_share", "expense", "refund")),
    )

    q = db.session.query(func.coalesce(func.sum(amount_col), 0.0)).filter(
        amount_col > 0,
        status_ok,
        inflow_condition,
    )

    # اگر enrollment_id هست و ستونش وجود دارد، دقیقاً همان را فیلتر کن
    if enrollment_id is not None and hasattr(Payment, "enrollment_id"):
        q = q.filter(Payment.enrollment_id == enrollment_id)
        return float(q.scalar() or 0.0)

    if student_id is not None and hasattr(Payment, "student_id"):
        q = q.filter(Payment.student_id == student_id)

    if course_id is not None and hasattr(Payment, "course_id"):
        # بعضی رکوردها course_id ندارند؛ حذفشان نکنیم
        q = q.filter(or_(Payment.course_id == course_id, Payment.course_id.is_(None)))

    return float(q.scalar() or 0.0)

def _sum_paid_mentor(course_id: int | None = None, mentor_id: int | None = None) -> float:
    """
    جمع پرداخت‌های انجام‌شده به منتور:
    - منبع اصلی: MentorPayment(kind='EXPENSE')  [+ فیلتر course_id اگر ستونش وجود داشت]
    - fallback: Payment(kind='mentor_share' & status in paid/settled)
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

    if total <= 0.0:
        q2 = db.session.query(func.coalesce(func.sum(Payment.amount), 0.0)).filter(
            func.lower(Payment.kind) == "mentor_share",
            func.coalesce(func.lower(Payment.status), "paid").in_(("paid", "settled")),
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
    # 1) ارتباط آی‌دی
    mid1 = getattr(c, "mentor_id", None)
    if mid1 is not None:
        try:
            if int(mid1) == int(m.id):
                return True
        except Exception:
            if str(mid1) == str(m.id):
                return True
    # 2) رابطه شیء
    mid2 = getattr(getattr(c, "mentor", None), "id", None)
    if mid2 is not None:
        try:
            if int(mid2) == int(m.id):
                return True
        except Exception:
            if str(mid2) == str(m.id):
                return True
    # 3) نام منتور
    c_name = _norm_text(getattr(c, "mentor_name", None))
    if c_name:
        m_full = _norm_text(getattr(m, "full_name", None))
        m_pair = _norm_text(f"{getattr(m,'first_name', '')} {getattr(m,'last_name','')}")
        if c_name and (c_name == m_full or c_name == m_pair):
            return True
    return False

def _plan_links(p):
    sid = getattr(p, "student_id", None)
    cid = getattr(p, "course_id", None)
    en_id = getattr(p, "enrollment_id", None)
    if (sid is None or cid is None) and en_id:
        en = Enrollment.query.get(en_id)
        if en:
            if sid is None:
                sid = getattr(en, "student_id", None)
            if cid is None:
                cid = getattr(en, "course_id", None)
    return sid, cid
def _sum_received_from_installments(
    course_id: int | None = None,
    student_id: int | None = None,
    enrollment_id: int | None = None,
) -> int:
    """
    جمع «دریافتی شهریه» صرفاً از روی اقساط پرداخت‌شده (Installment).
    فیلترها اختیاری‌اند و با تحمل لینک از Enrollment کار می‌کنند.
    """
    total = 0
    plans = InstallmentPlan.query.all()
    for p in plans:
        sid, cid, en_id = _plan_links(p)

        # فیلترهای ورودی
        if enrollment_id is not None and (en_id != enrollment_id):
            continue
        if student_id is not None and (sid != student_id):
            continue
        if course_id is not None and (cid != course_id):
            continue

        for inst in (getattr(p, "installments", []) or []):
            total += _inst_paid_amount(inst)
    return int(total)

def _student_course_installment_totals():
    acc = {}
    for p in InstallmentPlan.query.all():
        sid, cid = _plan_links(p)
        if not sid or not cid:
            continue
        key = (int(sid), int(cid))
        fee  = 0
        paid = 0
        for inst in (getattr(p, "installments", []) or []):
            fee  += _inst_total(inst)
            paid += _inst_paid_amount(inst)
        cur = acc.get(key, {"fee": 0, "paid": 0})
        cur["fee"]  += fee
        cur["paid"] += paid
        acc[key] = cur
    return acc

# =========================
# داشبورد تب‌محور (یک صفحه)
# =========================
@bp.get("/")
@login_required
def dashboard():
    today = date.today()
    start_month = date(today.year, today.month, 1)
    next_month = (start_month.replace(day=28) + timedelta(days=4)).replace(day=1)

    payments = Payment.query.all()
    per_inst = _student_course_installment_totals()

    # --- KPI: شهریه اسمی/دریافتی/مطالبات بر اساس اقساط
    total_face = float(sum(v.get("fee", 0) for v in per_inst.values()))
    total_paid = float(sum(v.get("paid", 0) for v in per_inst.values()))
    total_receivables = max(total_face - total_paid, 0.0)
    mtd_received = 0.0
    
    receipts_12m: dict[tuple[int, int], float] = defaultdict(float)

    print(f"دریافتی{total_receivables}")
    for p in payments:
        amt = _safe_num(getattr(p, "amount", None), 0.0)
        if amt <= 0:
            continue
        if not _is_paid(p):
            continue
        if not _is_inflow_kind(getattr(p, "kind", "")):
            continue

        paid_at = getattr(p, "paid_at", None) or getattr(p, "created_at", None)
        if isinstance(paid_at, date) and not isinstance(paid_at, datetime):
            paid_dt = datetime.combine(paid_at, datetime.min.time())
        else:
            paid_dt = paid_at or datetime.combine(today, datetime.min.time())

        total_receivables += amt
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

    # --- معوقات از روی اقساط ---
    # total_receivables = max(total_face - total_receivables, 0.0)

    # --- سررسید گذشته/۷ روز آینده (روی Payment‌های unpaid) ---
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

    # --- دوره‌های پرفروش ماه جاری (paid only) ---
    top_courses_mtd: dict[str, dict] = defaultdict(lambda: {"title": "—", "count": 0, "amount": 0.0})
    for p in payments:
        amt = _safe_num(getattr(p, "amount", None), 0.0)
        if amt <= 0 or not _is_paid(p) or not _is_inflow_kind(getattr(p, "kind", "")):
            continue
        paid_at = getattr(p, "paid_at", None) or getattr(p, "created_at", None)
        paid_date = paid_at.date() if isinstance(paid_at, datetime) else paid_at
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
    try:
        AssetModelPresent = True
        assets = Asset.query.order_by(Asset.id.desc()).all()
        assets_total = (
            db.session.query(func.coalesce(func.sum(Asset.purchase_price), 0))
            .scalar()
        )
    except Exception:
        # اگر مدل لود نشد
        AssetModelPresent = False
        assets = []
        assets_total = 0

    ctx = {
        # ... بقیهٔ کانتکست‌های قبلی ...
        "AssetModelPresent": AssetModelPresent,
        "assets": assets,
        "assets_total": assets_total,
    }

    # --- میانگین تأخیر وصول ---
    delays = []
    for p in payments:
        if _is_paid(p):
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

    # === تب «مطالبات دانشجو» (از اقساط) ===
    rec_items = []
    rows_base = (
        db.session.query(Enrollment, Course, Student)
        .join(Course, Course.id == Enrollment.course_id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(Enrollment.status.in_(("ACTIVE", "ONGOING")))
        .order_by(Course.id.desc())
        .all()
        )

    for en, co, st in rows_base:
        key = (int(st.id), int(co.id))
        fee = int(per_inst.get(key, {}).get("fee", 0))
        paid = int(per_inst.get(key, {}).get("paid", 0))
        remain = max(fee - paid, 0)

    # ✅ نمایش در کنسول
        print(
            f"[Student {st.id} - {st.first_name or ''} {st.last_name or ''}] "
            f"Course: {co.title} | Fee: {fee:,} | Paid: {paid:,} | Remain: {remain:,}"
            )

        rec_items.append(
            dict(
                en_id=en.id,
                student_name=(f"{st.first_name or ''} {st.last_name or ''}".strip() or f"دانشجو #{st.id}"),
                student_id=st.id,
                course_title=co.title,
                course_id=co.id,
                fee=fee,
                received=paid,
                remain=remain,
            )
        )

    rec_items.sort(key=lambda x: (-x["remain"], x["student_name"]))

    # === تب «دوره‌ها» ===
    course_rows = []
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
        face_total = _course_face_fee(c)
        received = _sum_paid_tuition(course_id=c.id)
        remain = max(face_total - received, 0.0)
        pct = _mentor_pct(c)
        mentor_share = face_total * pct
        m_ref = getattr(c, "mentor_id", None)
        if m_ref is None:
            m_ref = getattr(getattr(c, "mentor", None), "id", None)
        m_id = int(m_ref) if m_ref is not None else 0

        mentor_paid_total = mentor_paid_totals.get(m_id, 0.0)
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
        due = max(total_share_m - paid, 0.0)
        mentor_rows.append(dict(
            mentor=m,
            courses=len(mentor_courses),
            received=int(total_received_m),
            share=int(total_share_m),
            paid=int(paid),
            due=int(due),
        ))

    # === تب «اقساط» (فقط اقساط باز) ===
    inst_rows = []
    plans = InstallmentPlan.query.all()
    for plan in plans:
        # course_id ایمن
        cid = getattr(plan, "course_id", None)
        if not cid and getattr(plan, "enrollment_id", None):
            en = Enrollment.query.get(plan.enrollment_id)
            cid = en.course_id if en else None

        # عنوان دوره
        course_title = "—"
        if cid:
            c = Course.query.get(cid)
            if c:
                course_title = c.title

        # فقط اقساط باز/تسویه‌نشده را نمایش بده
        for inst in (plan.installments or []):
            if _is_installment_closed(inst):
                continue
            inst_rows.append(
                dict(
                    course_title=course_title,
                    title=plan.title or f"قسط #{inst.seq}",
                    due=inst.due_date.isoformat() if getattr(inst, "due_date", None) else "-",
                    amount=int(_inst_total(inst)),
                    overdue=(getattr(inst, "due_date", None) and inst.due_date < today),
                    status=(getattr(inst, "status", "PENDING") or "PENDING").upper(),
                )
            )

    # مرتب‌سازی اقساط باز
    inst_rows.sort(key=lambda x: (x["due"] is None, x["due"] or "", x["title"]))

    # ---- نمایش داشبورد
    return render_template(
        "finance/dashboard.html", **ctx,
        # KPI
        kpis=dict(
            total_face=int(total_face),
            total_received=int(total_paid),
            mtd_received=int(mtd_received),
            total_receivables=int(total_receivables),
            mtd_expense=int(mtd_expense),
            assets_total=int(assets_total),
            avg_delay_days=avg_delay_days,
            overdue_count=int(overdue_count),
            overdue_amount=int(overdue_amount),
        ),
        # سری و جداول
        monthly=monthly,
        top_courses_mtd=top_courses_mtd_list,
        expense_mtd_by_cat=expense_mtd_by_cat,
        expenses=expenses,
        aging_buckets=aging_buckets,
        upcoming_7=upcoming_7,
        # تب‌ها
        receivables=rec_items,
        courses=course_rows,
        mentors=mentor_rows,
        installments=inst_rows,
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

    # خواندن از اقساط تا با داشبورد/پروفایل یکسان باشد
    per_inst = _student_course_installment_totals()

    items = []
    for en, co, st in rows:
        key = (int(st.id), int(co.id))
        fee = int(per_inst.get(key, {}).get("fee", 0))
        paid = int(per_inst.get(key, {}).get("paid", 0))
        remain = max(fee - paid, 0)
        items.append(
            dict(
                en_id=en.id,
                student_name=(f"{st.first_name or ''} {st.last_name or ''}".strip() or f"دانشجو #{st.id}"),
                student_id=st.id,
                course_title=co.title,
                course_id=co.id,
                fee=fee,
                received=paid,
                remain=remain,
                balance=remain,
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
        due = max(total_share - paid, 0.0)

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
    """صفحه تفکیکی اقساط (بر مبنای Payment‌های شهریه معوق) — اگر لازم نداری، می‌توانیم با Installment هم‌راستا کنیم."""
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
    try:
            from hamafzar import db
            from hamafzar.app.models.asset import Asset
    except Exception:
    # fallback اگر ساختار ایمپورت کمی فرق داشت
        from app import db  # noqa: F401
        from app.models.asset import Asset  # noqa: F401


def _to_int(v, default=1):
    try:
        return int(v)
    except Exception:
        return default


def _to_decimal(v):
    if v in (None, "",):
        return None
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def _to_date(v):
    # انتظار: YYYY-MM-DD
    if not v:
        return None
    from datetime import datetime
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except Exception:
        return None


@bp.route("/assets", methods=["GET", "POST"])
def assets_index():
    """
    لیست + ثبت سریع دارایی
    """
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("نام دارایی الزامی است.", "danger")
            return redirect(url_for("finance.assets_index"))

        a = Asset(
            name=name,
            category=(request.form.get("category") or "").strip() or None,
            code=(request.form.get("code") or "").strip() or None,
            quantity=_to_int(request.form.get("quantity"), 1),
            unit=(request.form.get("unit") or "").strip() or None,
            location=(request.form.get("location") or "").strip() or None,
            status=(request.form.get("status") or "").strip() or None,
            purchase_date=_to_date(request.form.get("purchase_date")),
            purchase_price=_to_decimal(request.form.get("purchase_price")),
            notes=(request.form.get("notes") or "").strip() or None,
        )
        try:
            db.session.add(a)
            db.session.commit()
            flash("دارایی با موفقیت ثبت شد.", "success")
        except Exception as e:
            db.session.rollback()
            # نکته: اگر code یونیک باشد، درجِ تکراری خطا می‌دهد
            flash(f"خطا در ثبت دارایی: {e}", "danger")
        return redirect(url_for("finance.assets_index"))

    q = (request.args.get("q") or "").strip()
    qs = Asset.query.order_by(Asset.id.desc())
    if q:
        like = f"%{q}%"
        qs = qs.filter(
            or_(
                Asset.name.ilike(like),
                Asset.category.ilike(like),
                Asset.code.ilike(like),
                Asset.location.ilike(like),
                Asset.status.ilike(like),
            )
        )
    items = qs.all()
    return render_template("finance/assets.html", items=items, q=q)


@bp.route("/assets/<int:asset_id>/edit", methods=["POST"])
def assets_edit(asset_id):
    a = Asset.query.get_or_404(asset_id)
    a.name = (request.form.get("name") or "").strip() or a.name
    a.category = (request.form.get("category") or "").strip() or None
    a.code = (request.form.get("code") or "").strip() or None
    a.quantity = _to_int(request.form.get("quantity"), a.quantity or 1)
    a.unit = (request.form.get("unit") or "").strip() or None
    a.location = (request.form.get("location") or "").strip() or None
    a.status = (request.form.get("status") or "").strip() or None
    a.purchase_date = _to_date(request.form.get("purchase_date"))
    a.purchase_price = _to_decimal(request.form.get("purchase_price"))
    a.notes = (request.form.get("notes") or "").strip() or None
    try:
        db.session.commit()
        flash("دارایی ویرایش شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"خطا در ویرایش: {e}", "danger")
    return redirect(url_for("finance.assets_index"))


@bp.route("/assets/<int:asset_id>/delete", methods=["POST"])
def assets_delete(asset_id):
    a = Asset.query.get_or_404(asset_id)
    try:
        db.session.delete(a)
        db.session.commit()
        flash("دارایی حذف شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"حذف با خطا مواجه شد: {e}", "danger")
    return redirect(url_for("finance.assets_index"))