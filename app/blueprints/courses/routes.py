from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import func

from app.extensions import db
from app.models.course import Course
from app.models.mentor import Mentor
from app.models.core import Student
from app.models.enrollment import Enrollment

# اقساط و چک‌ها
from app.models.installment import Installment
from app.models.cheque import Cheque

bp = Blueprint("courses", __name__, url_prefix="/courses")


# ---------- Helpers ----------
def _parse_date(val: str | None):
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except Exception:
        return None


def _save_installments_for_course(course: Course):
    """
    داده‌های تب «اقساط» را برای دوره ذخیره می‌کند (Rebuild کامل).
    - اگر تیک اقساط نخورده: اقساط موجود حذف می‌شود و برمی‌گردیم.
    - اگر خورده: همه اقساط/چک‌های قبلی پاک و از صفر ساخته می‌شود.
    """
    is_installment = request.form.get("is_installment") == "1"

    # حذف امن اقساط/چک‌های قبلی این دوره
    prev = Installment.query.filter(Installment.course_id == course.id).all()
    for inst in prev:
        for ch in list(inst.cheques):
            db.session.delete(ch)
        db.session.delete(inst)

    if not is_installment:
        return

    titles  = request.form.getlist("inst_title[]")
    amounts = request.form.getlist("inst_amount[]")
    dues    = request.form.getlist("inst_due_date[]")
    methods = request.form.getlist("inst_method[]")

    ch_numbers = request.form.getlist("inst_cheque_number[]")
    ch_banks   = request.form.getlist("inst_bank_name[]")
    ch_issuers = request.form.getlist("inst_issuer_name[]")
    ch_issue   = request.form.getlist("inst_issue_date[]")
    ch_due     = request.form.getlist("inst_cheque_due_date[]")

    # کارمزد کلی (اختیاری)
    surcharge_percent = request.form.get("inst_surcharge_percent", type=float)
    if not surcharge_percent:  # '', 0, None => None
        surcharge_percent = None

    rows = max(len(titles), len(amounts), len(dues))
    for i in range(rows):
        title = (titles[i] if i < len(titles) else "").strip() or f"قسط #{i+1}"

        amt_raw = amounts[i] if i < len(amounts) else "0"
        try:
            amount = float(amt_raw or 0)
        except Exception:
            amount = 0.0

        due = _parse_date(dues[i] if i < len(dues) else None)
        method = (methods[i] if i < len(methods) else "").upper().strip() or None

        inst = Installment(
            course_id=course.id,
            title=title,
            amount=amount,
            due_date=due or date.today(),
            status="PENDING",
            method=method,
            surcharge_percent=surcharge_percent,
            surcharge_amount=(amount * (surcharge_percent / 100.0)) if surcharge_percent else None,
        )
        db.session.add(inst)
        db.session.flush()  # برای گرفتن inst.id

        # اگر روش CHEQUE است یا هرکدام از فیلدهای چک پر شده باشد، یک چک ثبت می‌کنیم
        has_any_cheque_field = any([
            (ch_numbers[i] if i < len(ch_numbers) else "").strip(),
            (ch_banks[i] if i < len(ch_banks) else "").strip(),
            (ch_issuers[i] if i < len(ch_issuers) else "").strip(),
            (ch_issue[i] if i < len(ch_issue) else "").strip(),
            (ch_due[i] if i < len(ch_due) else "").strip(),
        ])
        if method == "CHEQUE" or has_any_cheque_field:
            cheque = Cheque(
                installment_id=inst.id,
                cheque_number=(ch_numbers[i] if i < len(ch_numbers) else "").strip() or None,
                bank_name=(ch_banks[i] if i < len(ch_banks) else "").strip() or None,
                issuer_name=(ch_issuers[i] if i < len(ch_issuers) else "").strip() or None,
                issue_date=_parse_date(ch_issue[i] if i < len(ch_issue) else None),
                due_date=_parse_date(ch_due[i] if i < len(ch_due) else None),
                amount=amount,
                status="PENDING",
            )
            db.session.add(cheque)


# ---------- Routes ----------
@bp.get("/", endpoint="list")   # 👈 alias می‌سازد: courses.list
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 10

    base = Course.query
    if q:
        base = base.filter(Course.title.ilike(f"%{q}%"))

    base = base.order_by(Course.id.desc())

    # تلاش برای استفاده از paginate قدیمی Flask-SQLAlchemy
    items = []
    pagination = base.order_by(Course.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    items = pagination.items
    try:
        # Flask-SQLAlchemy < 3
        pagination = base.paginate(page=page, per_page=per_page, error_out=False)
        items = pagination.items
    except Exception:
        # فallback برای SQLAlchemy 2.x یا نبود paginate
        total = base.count()
        items = (
            base.limit(per_page)
                .offset((page - 1) * per_page)
                .all()
        )

        class SimplePagination:
            def __init__(self, page, per_page, total):
                self.page = page
                self.per_page = per_page
                self.total = total
                self.pages = (total // per_page) + (1 if total % per_page else 0)
                self.has_prev = page > 1
                self.has_next = page < self.pages if self.pages else False
                self.prev_num = page - 1 if self.has_prev else None
                self.next_num = page + 1 if self.has_next else None

            # برای سازگاری با بعضی تمپلیت‌ها
            def iter_pages(self, left_edge=2, left_current=2, right_current=2, right_edge=2):
                last = 0
                for num in range(1, (self.pages or 0) + 1):
                    if (num <= left_edge or
                        (num > self.page - left_current - 1 and num < self.page + right_current) or
                        num > (self.pages - right_edge)):
                        if last + 1 != num:
                            yield None
                        yield num
                        last = num

        pagination = SimplePagination(page, per_page, total)

    return render_template(
        "courses/index.html",
        items=items,
        pagination=pagination,
        q=q,
    )

@bp.get("/new")
@login_required
def new():
    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    save_action = url_for("courses.create")

    # مقداردهی اولیه تب اقساط
    ctx = dict(
        item=None,
        mentors=mentors,
        save_action=save_action,
        installments=[],
        is_installment=False,
        installments_count=None,
        inst_surcharge_percent=None,
    )
    return render_template("courses/form.html", **ctx)


@bp.post("/")
@login_required
def create():
    # ساخت دوره از تب‌های موجود فرم شما (فقط فیلدهای پایه به‌صورت نمونه):
    title = (request.form.get("title") or "").strip()
    mentor_id = request.form.get("mentor_id", type=int)
    status = (request.form.get("status") or "ACTIVE").upper().strip()

    c = Course(title=title, status=status)
    if mentor_id:
        c.mentor_id = mentor_id

    # TODO: سایر فیلدهای دوره را مطابق فرم موجودتان اینجا ست کنید.

    db.session.add(c)
    db.session.flush()  # نیاز به course.id برای اقساط

    # ذخیره تب «اقساط»
    _save_installments_for_course(c)

    db.session.commit()
    flash("دوره ثبت شد.", "success")
    return redirect(url_for("courses.edit", id=c.id))


@bp.get("/<int:id>/edit", endpoint="edit_form")
@login_required
def edit(id):
    c = Course.query.get_or_404(id)
    mentors = Mentor.query.order_by(Mentor.id.desc()).all()

    # آماده‌سازی تب اقساط برای فرم
    insts = (
        Installment.query
        .filter(Installment.course_id == c.id)
        .order_by(Installment.due_date.asc(), Installment.id.asc())
        .all()
    )
    is_installment = True if insts else False

    inst_list = []
    for inst in insts:
        inst_list.append(dict(
            title=inst.title,
            amount=int(inst.amount or 0),
            due_date=inst.due_date.isoformat() if inst.due_date else "",
            method=(inst.method or ""),
            cheque=(inst.cheques[0] if inst.cheques else None),
        ))

    ctx = dict(
        item=c,
        mentors=mentors,
        save_action=url_for("courses.update", id=c.id),
        installments=inst_list,
        is_installment=is_installment,
        installments_count=len(inst_list) if inst_list else None,
        inst_surcharge_percent=insts[0].surcharge_percent if insts else None,
    )
    return render_template("courses/form.html", **ctx)


@bp.post("/<int:id>")
@login_required
def update(id):
    c = Course.query.get_or_404(id)

    # بروزرسانی فیلدهای پایه (بقیه را طبق فرم موجودتان اضافه کنید)
    title = (request.form.get("title") or "").strip()
    if title:
        c.title = title

    mentor_id = request.form.get("mentor_id", type=int)
    if mentor_id is not None:
        c.mentor_id = mentor_id

    # بروزرسانی تب «اقساط»
    _save_installments_for_course(c)

    db.session.commit()
    flash("دوره بروزرسانی شد.", "success")
    return redirect(url_for("courses.edit", id=c.id))

@bp.get("/", endpoint="index")
@login_required
def courses_index():
    q = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 10

    base = Course.query
    if q:
        base = base.filter(Course.title.ilike(f"%{q}%"))

    pagination = base.order_by(Course.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    items = pagination.items
    return render_template("courses/index.html", items=items, pagination=pagination, q=q)



