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
from app.models.installment_cheque import InstallmentCheque
from sqlalchemy import and_ 
from app.utils.decorators import role_required
bp = Blueprint("finance", __name__, url_prefix="/finance")

# --------- مدل‌های اختیاری ---------
try:
    from app.models.expense import Expense  # type: ignore
except Exception:  # noqa
    Expense = None  # type: ignore


# ---------------- Helpers ----------------
def _has_col(model, name: str) -> bool:
    try:
        return hasattr(model, "__table__") and name in model.__table__.c
    except Exception:
        return hasattr(model, name)

def _get_first(exp, names, default=None):
    for n in names:
        if _has_col(Expense, n):
            return getattr(exp, n, default)
    return default

def _set_if_has(exp, name: str, value):
    if _has_col(Expense, name):
        setattr(exp, name, value)

def _parse_date_local(s: str | None):
    if not s:
        return None
    s = s.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None
def _parse_date_local(s: str | None):
    if not s:
        return None
    s = s.strip()
    try:
        return datetime.strptime(s.replace("/", "-"), "%Y-%m-%d").date()
    except Exception:
        return None
def _plans_for_enrollment(en: Enrollment):
    """پیدا کردن پلن/پلن‌های قسط برای یک ثبت‌نام با تحمل لینک."""
    plans = []
    # اول مستقیم با enrollment_id (اگر ستون هست)
    if hasattr(InstallmentPlan, "enrollment_id"):
        plans = InstallmentPlan.query.filter(InstallmentPlan.enrollment_id == en.id).all()
        if plans:
            return plans
    # fallback: با student_id + course_id
    q = InstallmentPlan.query
    # اگر ستون‌های student_id / course_id روی پلن موجودند
    if hasattr(InstallmentPlan, "student_id") and hasattr(InstallmentPlan, "course_id"):
        plans = q.filter(
            InstallmentPlan.student_id == en.student_id,
            InstallmentPlan.course_id == en.course_id,
        ).all()
        if plans:
            return plans
    # آخرین تحمل: join با Enrollment (اگر enrollment_id روی پلن هست اما مقدار نداشت)
    if hasattr(InstallmentPlan, "enrollment_id"):
        plans = (
            InstallmentPlan.query
            .join(Enrollment, Enrollment.id == InstallmentPlan.enrollment_id)
            .filter(Enrollment.student_id == en.student_id,
                    Enrollment.course_id == en.course_id)
            .all()
        )
    return plans or []


def _enrollment_financials(en: Enrollment) -> tuple[int, int]:
    """
    خروجی: (fee_for_this_enrollment, paid_for_this_enrollment)
    - اگر اقساط داشته باشد از اقساط می‌خوانیم.
    - وگرنه شهریهٔ نقدی دانشجو (= نرخ دوره) و دریافتی از Payment.
    """
    fee = 0
    paid = 0

    # تلاش برای یافتن اقساط
    plans = _plans_for_enrollment(en)
    if plans:
        for p in plans:
            for inst in (getattr(p, "installments", []) or []):
                fee  += _inst_total(inst)
                paid += _inst_paid_amount(inst)
        return int(fee), int(paid)

    # نقدی: هزینهٔ هر دانشجو = tuition_per_student
    c = Course.query.get(en.course_id)
    per = float(getattr(c, "tuition_per_student", 0) or 0)
    fee = int(per)

    # دریافتی نقدی این ثبت‌نام
    if hasattr(Payment, "enrollment_id"):
        paid = int(_sum_paid_tuition(enrollment_id=en.id))
    else:
        paid = int(_sum_paid_tuition(student_id=en.student_id, course_id=en.course_id))

    return int(fee), int(paid)


def _mentor_financials(m: Mentor) -> dict:
    """
    محاسبات تجمیعی برای یک منتور با منطق ترکیبی اقساط/نقدی به ازای هر دانشجو.
    خروجی: dict(face_total, received_total, share_total, paid_to_mentor, due, courses_count)
    """
    all_courses = Course.query.all()
    # دوره‌های منتور طبق تحمل‌های فعلی پروژه
    mentor_courses = [c for c in all_courses if _course_belongs_to_mentor(c, m)]

    face_total = 0  # مجموع هزینهٔ کل برای همهٔ دانشجوهای دوره‌های منتور
    received_total = 0  # مجموع دریافتی واقعی از دانشجوها
    share_total = 0  # سهم منتور از face_total با درصد هر دوره
    courses_count = len(mentor_courses)

    for c in mentor_courses:
        # ثبت‌نام‌های فعال/جاری این دوره
        ens = (Enrollment.query
               .filter(Enrollment.course_id == c.id,
                       Enrollment.status.in_(("ACTIVE", "ONGOING")))
               .all())

        pct = _mentor_pct(c)  # درصد سهم منتور برای همین دوره
        for en in ens:
            fee_en, paid_en = _enrollment_financials(en)
            face_total     += fee_en
            received_total += paid_en
            share_total    += fee_en * pct

    paid_to_mentor = _sum_paid_mentor(mentor_id=m.id)  # پرداخت‌های انجام‌شده به منتور
    due = max(int(share_total) - int(paid_to_mentor), 0)

    return dict(
        face_total=int(face_total),
        received_total=int(received_total),
        share_total=int(share_total),
        paid_to_mentor=int(paid_to_mentor),
        due=int(due),
        courses_count=courses_count,
    )
# --- تشخیص و تجمیع اقساط برای یک دوره ---

def _has_installments_for_course(course_id: int) -> bool:
    # اگر ستون course_id در InstallmentPlan هست، سریع‌ترین مسیر
    if hasattr(InstallmentPlan, "course_id"):
        exists = db.session.query(InstallmentPlan.id).filter(InstallmentPlan.course_id == course_id).first()
        if exists:
            return True
    # تحمل لینک از enrollment
    if hasattr(InstallmentPlan, "enrollment_id"):
        q = (
            db.session.query(InstallmentPlan.id)
            .join(Enrollment, Enrollment.id == InstallmentPlan.enrollment_id)
            .filter(Enrollment.course_id == course_id)
        )
        if q.first():
            return True
    return False


def _course_installment_totals(course_id: int) -> tuple[int, int]:
    """fee_total, paid_total بر مبنای اقساط همان دوره (تحمل لینک enrollment)"""
    fee_total = 0
    paid_total = 0
    if hasattr(InstallmentPlan, "course_id"):
        plans = InstallmentPlan.query.filter(InstallmentPlan.course_id == course_id).all()
    else:
        plans = (
            InstallmentPlan.query.join(Enrollment, Enrollment.id == InstallmentPlan.enrollment_id)
            .filter(Enrollment.course_id == course_id)
            .all()
        )
    for p in plans:
        for inst in (getattr(p, "installments", []) or []):
            fee_total += _inst_total(inst)
            paid_total += _inst_paid_amount(inst)
    return int(fee_total), int(paid_total)


def _course_financials(c: Course) -> dict:
    """
    محاسبه‌ی تجمیعی مالی دوره با پشتیبانی از حالت ترکیبی:
    - برای هر Enrollment فعال/درحال‌برگزاری:
        * اگر اقساط دارد: از اقساط fee/paid بگیر
        * اگر ندارد: fee = tuition_per_student ، paid = پرداخت‌های نقدی همان enrollment
    """
    # نقشه‌ی اقساط به تفکیک (student_id, course_id)
    per_inst = _student_course_installment_totals()

    fee_total = 0
    paid_total = 0

    # ثبت‌نام‌های فعال این دوره
    ens = (
        Enrollment.query
        .filter(Enrollment.course_id == c.id,
                Enrollment.status.in_(("ACTIVE", "ONGOING")))
        .all()
    )

    per_student = float(getattr(c, "tuition_per_student", 0) or 0)

    for en in ens:
        key = (int(getattr(en, "student_id")), int(c.id))
        inst_info = per_inst.get(key)

        if inst_info:  # این دانشجو برای این دوره قسط دارد
            fee_total  += int(inst_info.get("fee", 0) or 0)
            paid_total += int(inst_info.get("paid", 0) or 0)
        else:         # نقدی
            fee_total  += int(per_student)
            paid_total += int(_sum_paid_tuition(enrollment_id=en.id))

    remain = max(fee_total - paid_total, 0)
    return {"fee": int(fee_total), "paid": int(paid_total), "remain": int(remain)}


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
    status_ok = func.coalesce(func.lower(getattr(Payment, "status")), "pending").in_(("paid", "settled"))
    kind_col = func.lower(getattr(Payment, "kind"))
    inflow_condition = or_(kind_col.is_(None), ~kind_col.in_(("mentor_share", "expense", "refund")))

    q = db.session.query(func.coalesce(func.sum(amount_col), 0.0)).filter(
        amount_col > 0, status_ok, inflow_condition
    )

    if enrollment_id is not None and hasattr(Payment, "enrollment_id"):
        q = q.filter(Payment.enrollment_id == enrollment_id)
        return float(q.scalar() or 0.0)

    if student_id is not None and hasattr(Payment, "student_id"):
        q = q.filter(Payment.student_id == student_id)

    if course_id is not None and hasattr(Payment, "course_id"):
        q = q.filter(or_(Payment.course_id == course_id, Payment.course_id.is_(None)))

    return float(q.scalar() or 0.0)


def _sum_paid_mentor(course_id: int | None = None, mentor_id: int | None = None) -> float:
    """
    جمع پرداخت‌های انجام‌شده به منتور:
    - منبع اصلی: MentorPayment(kind='EXPENSE')
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
    """جمع دریافتی شهریه صرفاً از روی اقساط پرداخت‌شده (Installment)."""
    total = 0
    plans = InstallmentPlan.query.all()
    for p in plans:
        sid, cid, en_id = _plan_links(p)
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
        fee = 0
        paid = 0
        for inst in (getattr(p, "installments", []) or []):
            fee += _inst_total(inst)
            paid += _inst_paid_amount(inst)
        cur = acc.get(key, {"fee": 0, "paid": 0})
        cur["fee"] += fee
        cur["paid"] += paid
        acc[key] = cur
    return acc


# =========================
# داشبورد تب‌محور (یک صفحه)
# =========================
@bp.get("/")
@login_required
@role_required(["ADMIN"])
def dashboard():
    today = date.today()
    start_month = date(today.year, today.month, 1)
    next_month = (start_month.replace(day=28) + timedelta(days=4)).replace(day=1)

    payments = Payment.query.all()

    # --- KPI: شهریه اسمی/دریافتی/مطالبات (قاعده اقساط/نقدی) ---
    total_face = 0.0
    total_paid = 0.0
    for c in Course.query.all():
        cf = _course_financials(c)
        total_face += cf["fee"]
        total_paid += cf["paid"]
    total_receivables = max(total_face - total_paid, 0.0)

    mtd_received = 0.0
    receipts_12m: dict[tuple[int, int], float] = defaultdict(float)
    # فقط برای نمودار و MTD از payments استفاده می‌کنیم؛ دیگر به receivables دست نمی‌زنیم
    for p in payments:
        amt = _safe_num(getattr(p, "amount", None), 0.0)
        if amt <= 0 or not _is_paid(p) or not _is_inflow_kind(getattr(p, "kind", "")):
            continue
        paid_at = getattr(p, "paid_at", None) or getattr(p, "created_at", None)
        if isinstance(paid_at, date) and not isinstance(paid_at, datetime):
            paid_dt = datetime.combine(paid_at, datetime.min.time())
        else:
            paid_dt = paid_at or datetime.combine(today, datetime.min.time())
        if start_month <= paid_dt.date() < next_month:
            mtd_received += amt
        receipts_12m[(paid_dt.year, paid_dt.month)] += amt

    # --- هزینه‌ها ---
    mtd_expense = 0.0
    expenses_total = 0.0
    expense_mtd_by_cat: dict[str, float] = defaultdict(float)
    expenses = []

    if Expense:
    # مرتب‌سازی ایمن فقط با ستون‌هایی که قطعاً در مدل وجود دارند
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

    expenses = q.limit(100).all()

    for ex in expenses:
        # مبلغ کل: amount_total اگر نبود، از amount_net+... حساب می‌کنیم
        net = _safe_num(getattr(ex, "amount_net", None), 0.0)
        vat = _safe_num(getattr(ex, "vat_rate", None), 0.0)
        sur = _safe_num(getattr(ex, "surcharge_percent", None), 0.0)
        total_calc = net + (net * vat / 100.0) + (net * sur / 100.0)
        ex_amt = _safe_num(getattr(ex, "amount_total", None), total_calc)

        expenses_total += ex_amt

        paid_at = getattr(ex, "paid_at", None) or getattr(ex, "created_at", None)
        paid_date = paid_at.date() if isinstance(paid_at, datetime) else paid_at
        cat = (getattr(ex, "category", None) or "سایر").upper()

        if paid_date and (start_month <= paid_date < next_month):
                mtd_expense += ex_amt
                expense_mtd_by_cat[cat] += ex_amt

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
        assets_total = db.session.query(
            func.coalesce(
                func.sum(func.coalesce(Asset.purchase_price, 0) * func.coalesce(Asset.quantity, 0)),
                0,
            )
        ).scalar()
    except Exception:
        AssetModelPresent = False
        assets = []
        assets_total = 0

    ctx = {
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
    per_inst = _student_course_installment_totals()
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
        print(f"[Student {st.id} - {st.first_name or ''} {st.last_name or ''}] Course: {co.title} | Fee: {fee:,} | Paid: {paid:,} | Remain: {remain:,}")
        fee, paid = _enrollment_financials(en)
        fee = int(fee or 0)
        paid = int(paid or 0)
        remain = max(fee - paid, 0)
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
    for c in Course.query.order_by(Course.id.desc()).all():
        cf = _course_financials(c)
        face_total = cf["fee"]
        received = cf["paid"]
        remain = cf["remain"]

        pct = _mentor_pct(c)
        mentor_share = face_total * pct

        m_ref = getattr(c, "mentor_id", None)
        if m_ref is None:
            m_ref = getattr(getattr(c, "mentor", None), "id", None)

        mentor_paid_total = _sum_paid_mentor(course_id=c.id, mentor_id=(int(m_ref) if m_ref is not None else None))
        mentor_due = max(int(mentor_share) - int(mentor_paid_total), 0)

        course_rows.append(
            dict(
                course=c,
                students=_active_students_count(c.id),
                face=int(face_total),
                received=int(received),
                remain=int(remain),
                mentor_share=int(mentor_share),
                mentor_paid=int(mentor_paid_total),
                mentor_due=int(mentor_due),
            )
        )

    # === تب «منتورها» ===
    mentor_rows = []
    for m in Mentor.query.order_by(Mentor.id.desc()).all():
        mf = _mentor_financials(m)
        mentor_rows.append(dict(
            mentor=m,
            courses=mf["courses_count"],
            received=mf["received_total"],
            share=mf["share_total"],
            paid=mf["paid_to_mentor"],
            due=mf["due"],
        ))


    # === تب «اقساط» (فقط اقساط باز) ===
    inst_rows = []
    plans = InstallmentPlan.query.all()
    for plan in plans:
        cid = getattr(plan, "course_id", None)
        if not cid and getattr(plan, "enrollment_id", None):
            en = Enrollment.query.get(plan.enrollment_id)
            cid = en.course_id if en else None

        course_title = "—"
        if cid:
            c = Course.query.get(cid)
            if c:
                course_title = c.title

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
    inst_rows.sort(key=lambda x: (x["due"] is None, x["due"] or "", x["title"]))

    # ---- نمایش داشبورد
    return render_template(
        "finance/dashboard.html",
        **ctx,
        # KPI
        kpis=dict(
            total_face=int(total_face),
            total_received=int(total_paid),
            mtd_received=int(mtd_received),
            total_receivables=int(total_receivables),
            mtd_expense=int(mtd_expense),
            total_expense=int(expenses_total), 
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
        mtd_expense=int(mtd_expense),
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
@role_required(["ADMIN"])
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
@role_required(["ADMIN"])
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
        cf = _course_financials(c)
        face_total = cf["fee"]
        received   = cf["paid"]
        remain     = cf["remain"]

        pct = _mentor_pct(c)
        mentor_share = int(face_total * pct)

        # پرداختی واقعی به منتور برای همین دوره
        m_ref = getattr(c, "mentor_id", None)
        if m_ref is None:
            m_ref = getattr(getattr(c, "mentor", None), "id", None)
        paid_to_mentor = _sum_paid_mentor(course_id=c.id,
                                      mentor_id=(int(m_ref) if m_ref is not None else None))
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
@role_required(["ADMIN"])
def mentors_report():
    rows = []
    for m in Mentor.query.order_by(Mentor.id.desc()).all():
        mf = _mentor_financials(m)
        rows.append({
            "mentor": m,
            "courses": mf["courses_count"],
            "received": mf["received_total"],
            "share": mf["share_total"],
            "paid": mf["paid_to_mentor"],
            "due": mf["due"],
        })
    return render_template("finance/mentors.html", items=rows)


@bp.get("/installments")
@login_required
@role_required(["ADMIN"])
def installments():
    """صفحه اقساط باز بر مبنای InstallmentPlan/Installment + مدیریت چک‌ها"""
    today = date.today()
    items = []

    plans = InstallmentPlan.query.all()
    inst_ids = []

    for plan in plans:
        # course_id ایمن
        cid = getattr(plan, "course_id", None)
        if not cid and getattr(plan, "enrollment_id", None):
            en = Enrollment.query.get(plan.enrollment_id)
            cid = en.course_id if en else None

        course_title = "—"
        if cid:
            c = Course.query.get(cid)
            if c:
                course_title = c.title

        for inst in (plan.installments or []):
            # فقط اقساط باز
            total = (getattr(inst, "amount_total", None)
                     or (getattr(inst, "amount_base", 0) or 0) + (getattr(inst, "cheque_fee_amount", 0) or 0)) or 0
            paid = 0
            for attr in ("amount_paid", "paid_amount", "amount_received"):
                v = getattr(inst, attr, None)
                if v is not None:
                    try:
                        paid = int(v)
                        break
                    except Exception:
                        pass
            status = (getattr(inst, "status", "PENDING") or "PENDING").upper()
            is_closed = (paid >= int(total)) or (status in {"PAID", "SETTLED"})
            if is_closed:
                continue

            inst_id = int(getattr(inst, "id"))
            inst_ids.append(inst_id)

            due_dt = getattr(inst, "due_date", None)
            due_str = due_dt.isoformat() if due_dt else "-"
            overdue = bool(due_dt and (due_dt < today))

            items.append(dict(
                inst_id=inst_id,
                course_title=course_title,
                title=plan.title or f"قسط #{getattr(inst, 'seq', '') or inst_id}",
                due=due_str,
                amount=int(total),
                overdue=overdue,
                status=status,
            ))

    # چک‌های هر قسط
    cheques_by_inst = {}
    if inst_ids:
        rows = InstallmentCheque.query.filter(InstallmentCheque.installment_id.in_(inst_ids)).all()
        for ch in rows:
            cheques_by_inst.setdefault(int(ch.installment_id), []).append(ch)

    return render_template("finance/installments.html", items=items, cheques_by_inst=cheques_by_inst)


# ------------------------ Expenses (costs) ------------------------
@bp.get("/expenses")
@login_required
@role_required(["ADMIN"])
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
@role_required(["ADMIN"])
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
@role_required(["ADMIN"])
def assets_page():
    items = (
        Asset.query
        .order_by(
            Asset.purchase_date.desc().nullslast(),
            Asset.created_at.desc().nullslast(),
            Asset.id.desc()
        )
        .all()
    )
    return render_template("finance/assets.html", items=items)


@bp.post("/assets/new")
@login_required
@role_required(["ADMIN"])
def assets_new():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("نام دارایی الزامی است.", "danger")
        return redirect(url_for("finance.assets_page"))

    category = (request.form.get("category") or "").strip() or None
    code = (request.form.get("code") or "").strip() or None
    quantity = request.form.get("quantity", type=int) or 1
    unit = (request.form.get("unit") or "").strip() or None
    location = (request.form.get("location") or "").strip() or None
    status = (request.form.get("status") or "").strip() or None

    purchase_price_raw = (request.form.get("purchase_price") or "").strip()
    purchase_price = None
    if purchase_price_raw:
        try:
            purchase_price = float(purchase_price_raw.replace(",", ""))
        except Exception:
            purchase_price = None

    purchase_date = None
    purchase_date_str = (request.form.get("purchase_date") or "").strip()
    if purchase_date_str:
        try:
            purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
        except Exception:
            purchase_date = None

    notes = (request.form.get("notes") or "").strip() or None

    a = Asset(
        name=name,
        category=category,
        code=code,
        quantity=quantity,
        unit=unit,
        location=location,
        status=status,
        purchase_date=purchase_date,
        purchase_price=purchase_price,
        notes=notes,
    )
    try:
        db.session.add(a)
        db.session.commit()
        flash("دارایی با موفقیت ثبت شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"خطا در ثبت دارایی: {e}", "danger")

    return redirect(url_for("finance.assets_page"))


@bp.post("/assets/<int:asset_id>/edit")
@login_required
@role_required(["ADMIN"])
def assets_edit(asset_id):
    a = Asset.query.get_or_404(asset_id)

    name = (request.form.get("name") or "").strip()
    if name:
        a.name = name

    a.category = (request.form.get("category") or "").strip() or None
    a.code = (request.form.get("code") or "").strip() or None
    a.quantity = request.form.get("quantity", type=int) or (a.quantity or 1)
    a.unit = (request.form.get("unit") or "").strip() or None
    a.location = (request.form.get("location") or "").strip() or None
    a.status = (request.form.get("status") or "").strip() or None

    purchase_price_raw = (request.form.get("purchase_price") or "").strip()
    if purchase_price_raw != "":
        try:
            a.purchase_price = float(purchase_price_raw.replace(",", ""))
        except Exception:
            pass

    purchase_date_str = (request.form.get("purchase_date") or "").strip()
    if purchase_date_str:
        try:
            a.purchase_date = datetime.strptime(purchase_date_str, "%Y-%m-%d").date()
        except Exception:
            pass

    a.notes = (request.form.get("notes") or "").strip() or None

    try:
        db.session.commit()
        flash("دارایی ویرایش شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"خطا در ویرایش: {e}", "danger")

    return redirect(url_for("finance.assets_page"))


@bp.post("/assets/<int:asset_id>/delete")
@login_required
@role_required(["ADMIN"])
def assets_delete(asset_id):
    a = Asset.query.get_or_404(asset_id)
    try:
        db.session.delete(a)
        db.session.commit()
        flash("دارایی حذف شد.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"حذف با خطا مواجه شد: {e}", "danger")
    return redirect(url_for("finance.assets_page"))


@bp.post("/expenses/<int:expense_id>/edit")
@login_required
@role_required(["ADMIN"])
def expenses_edit(expense_id):
    exp = Expense.query.get_or_404(expense_id)
    f = request.form

    # ورودی‌های متنی
    title    = (f.get("title") or "").strip()
    category = (f.get("category") or "").strip() or None
    note     = (f.get("note") or "").strip() or None
    
    # اعداد – همیشه عدد معتبر تولید کنیم
    def _to_num(name, default=0.0):
        try:
            v = f.get(name, "").strip()
            return float(v) if v != "" else float(default)
        except Exception:
            return float(default)

    amount_net         = _to_num("amount_net", _get_first(exp, ["amount_net","amount_base"], 0))
    vat_rate           = _to_num("vat_rate", _get_first(exp, ["vat_rate","vat_percent","tax_rate","tax_percent"], 0))
    surcharge_percent  = _to_num("surcharge_percent", _get_first(exp, ["surcharge_percent","fee_percent","service_fee_percent"], 0))

    # روش پرداخت/وضعیت
    pm = (f.get("payment_method") or _get_first(exp, ["payment_method","method"], "CASH")).upper()
    if pm not in ("CASH", "CARD", "TRANSFER", "CHEQUE"):
        pm = "CASH"

    status = (f.get("status") or _get_first(exp, ["status"], "PAID")).upper()
    if status not in ("PAID", "PENDING"):
        status = "PAID"

    # دوره (اختیاری)
    course_id = None
    raw_cid = f.get("course_id")
    if raw_cid not in (None, "", "None"):
        try:
            course_id = int(raw_cid)
            if not Course.query.get(course_id):
                flash("دوره‌ی انتخاب‌شده معتبر نیست.", "error")
                return redirect(request.referrer or url_for("finance.expenses_page"))
        except Exception:
            flash("شناسه‌ی دوره نامعتبر است.", "error")
            return redirect(request.referrer or url_for("finance.expenses_page"))

    # محاسبه مبلغ کل سمت سرور
    amount_total = amount_net + (amount_net * vat_rate / 100.0) + (amount_net * surcharge_percent / 100.0)
    try:
        amount_total = int(round(amount_total))
    except Exception:
        pass

    # اعمال به مدل – فقط ستون‌های موجود را ست کن
    if title:
        _set_if_has(exp, "title", title)
    _set_if_has(exp, "category", category)
    _set_if_has(exp, "note", note)

    # مبلغ‌ها (نام‌های مختلف)
    if _has_col(Expense, "amount_net"):
        exp.amount_net = amount_net
    elif _has_col(Expense, "amount_base"):
        exp.amount_base = amount_net
    # اگر هیچ‌کدام نبود، بعداً amount/amount_total را ست می‌کنیم

    # نرخ‌ها
    for cand in ("vat_rate","vat_percent","tax_rate","tax_percent"):
        _set_if_has(exp, cand, vat_rate)
    for cand in ("surcharge_percent","fee_percent","service_fee_percent"):
        _set_if_has(exp, cand, surcharge_percent)

    # مبلغ کل (نام‌های مختلف)
    if _has_col(Expense, "amount_total"):
        exp.amount_total = amount_total
    elif _has_col(Expense, "total_amount"):
        exp.total_amount = amount_total
    elif _has_col(Expense, "gross_amount"):
        exp.gross_amount = amount_total
    elif _has_col(Expense, "amount"):
        exp.amount = amount_total  # مدل‌هایی که فقط یک فیلد amount دارند

    # روش پرداخت/وضعیت/دوره
    _set_if_has(exp, "payment_method", pm)
    _set_if_has(exp, "status", status)
    _set_if_has(exp, "course_id", course_id)

    # paid_at: سازگار با وضعیت
    if _has_col(Expense, "paid_at"):
        if status == "PAID" and getattr(exp, "paid_at", None) is None:
            exp.paid_at = datetime.utcnow()
        if status == "PENDING":
            exp.paid_at = None

    # فیلدهای چک – فقط اگر در مدل وجود داشته باشد
    cheque_number = (f.get("cheque_number") or "").strip() or None
    bank_name     = (f.get("bank_name") or "").strip() or None
    issuer_name   = (f.get("issuer_name") or "").strip() or None
    issue_date    = _parse_date_local(f.get("issue_date"))
    due_date      = _parse_date_local(f.get("due_date"))
    cheque_status = (f.get("cheque_status") or "").strip() or None

    if pm == "CHEQUE":
        for name, val in (
            ("cheque_number", cheque_number),
            ("bank_name", bank_name),
            ("issuer_name", issuer_name),
            ("issue_date", issue_date),
            ("due_date", due_date),
            ("cheque_status", cheque_status),
        ):
            _set_if_has(exp, name, val)
    else:
        # پاک‌سازی فیلدهای چک در صورت تغییر روش
        for name in ("cheque_number","bank_name","issuer_name","cheque_status"):
            if _has_col(Expense, name):
                setattr(exp, name, None)
        for name in ("issue_date","due_date"):
            if _has_col(Expense, name):
                setattr(exp, name, None)

    db.session.commit()
    flash("ویرایش هزینه با موفقیت ذخیره شد.", "success")
    return redirect(request.referrer or url_for("finance.expenses_page"))

@bp.post("/expenses/<int:expense_id>/delete")
@login_required
@role_required(["ADMIN"])
def expenses_delete(expense_id):
    exp = Expense.query.get_or_404(expense_id)
    db.session.delete(exp)
    db.session.commit()
    flash("هزینه حذف شد.", "info")
    return redirect(request.referrer or url_for("finance.expenses_page"))