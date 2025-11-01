# app/blueprints/mentors/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import func, literal
from sqlalchemy.orm.attributes import InstrumentedAttribute
from ...extensions import db
from ...models.mentor import Mentor
from ...models.course import Course
from ...models.enrollment import Enrollment
from ...models.mentor_payment import MentorPayment
from ...utils.files import save_mentor_avatar  # همان util موجود

bp = Blueprint("mentors", __name__, url_prefix="/mentors")


# -------------------------------
# Helpers
# -------------------------------
def _sa_col_or_literal(model, attr_name: str, default_value=0):
    """اگر attr ستونی از نوع SQLAlchemy نبود، literal(default) بده."""
    attr = getattr(model, attr_name, None)
    return attr if isinstance(attr, InstrumentedAttribute) else literal(default_value)

def _first_existing_column(model, candidates, default_value=0):
    """اولین ستونِ واقعی را برگردان؛ در غیر اینصورت literal(default)."""
    for name in candidates:
        attr = getattr(model, name, None)
        if isinstance(attr, InstrumentedAttribute):
            return attr
    return literal(default_value)


# -------------------------------
# Finance summary (used by edit.html JS -> /mentors/<id>/finance/summary)
# -------------------------------
def _mentor_finance_summary(mentor_id: int):
    """
    items: [
      {course_id, course_title, students, fee_per_student, share_percent, income_total, mentor_share}
    ]
    totals: { income_total, share_total, paid_total, balance }
    """
    # ستون واقعی شهریه هر دانشجو
    fee_col   = _first_existing_column(Course, ["tuition_per_student"], 0)
    share_col = _sa_col_or_literal(Course, "mentor_share_percent", 0)

    # فقط ثبت‌نام‌های ACTIVE شمرده شوند
    rows = (
        db.session.query(
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            func.coalesce(fee_col, 0).label("fee_per_student"),
            func.coalesce(share_col, 0).label("share_percent"),
            func.count(Enrollment.id).label("students_count"),
        )
        .outerjoin(Enrollment, (Enrollment.course_id == Course.id) & (Enrollment.status == "ACTIVE"))
        .filter(Course.mentor_id == mentor_id)
        .group_by(Course.id)
        .all()
    )

    items = []
    income_total = 0
    share_total  = 0

    for r in rows:
        students = int(r.students_count or 0)       # تعداد دانشجوی ACTIVE
        fee      = int(r.fee_per_student or 0)      # شهریه هر دانشجو
        share_pr = float(r.share_percent or 0)      # درصد سهم منتور

        income = students * fee                     # درآمد کل
        share  = int(round(income * (share_pr / 100.0)))  # سهم منتور

        items.append({
            "course_id": r.course_id,
            "course_title": r.course_title,
            "students": students,
            "fee_per_student": fee,
            "share_percent": share_pr,
            "income_total": income,
            "mentor_share": share,
        })

        income_total += income
        share_total  += share

    # مجموع پرداخت‌های واقعی ثبت‌شده برای منتور (فقط EXPENSE = پرداخت به منتور)
    paid_total = (
        db.session.query(func.coalesce(func.sum(MentorPayment.amount), 0))
        .filter(MentorPayment.mentor_id == mentor_id, MentorPayment.kind == "EXPENSE")
        .scalar()
    ) or 0

    balance = int(share_total) - int(paid_total)

    return {
        "items": items,
        "totals": {
            "income_total": int(income_total),
            "share_total":  int(share_total),
            "paid_total":   int(paid_total),
            "balance":      int(balance),
        },
    }


@bp.get("/<int:mentor_id>/finance/summary")
@login_required
def finance_summary(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    return jsonify(_mentor_finance_summary(mentor_id))


# -------------------------------
# List
# -------------------------------
@bp.get("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    query = Mentor.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Mentor.first_name.ilike(like)) |
            (Mentor.last_name.ilike(like)) |
            (Mentor.email.ilike(like)) |
            (Mentor.phone.ilike(like))
        )
    mentors = query.order_by(Mentor.created_at.desc()).all()
    return render_template("mentors/index.html", mentors=mentors, q=q)


# -------------------------------
# Create (GET form.html) + POST
# -------------------------------
@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_form():
    if request.method == "POST":
        f = request.form
        first = (f.get("first_name") or "").strip()
        last  = (f.get("last_name")  or "").strip()
        email = (f.get("email")      or "").strip() or None
        phone = (f.get("phone")      or "").strip() or None

        if not first or not last:
            flash("نام و نام خانوادگی الزامی است.", "error")
            return redirect(url_for("mentors.create_form"))

        m = Mentor(first_name=first, last_name=last, email=email, phone=phone)
        db.session.add(m)
        db.session.commit()

        file = request.files.get("avatar")
        if file and file.filename:
            rel = save_mentor_avatar(file, m.id)
            if rel:
                m.avatar = rel
                db.session.commit()

        flash("منتور با موفقیت ایجاد شد.", "success")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    return render_template("mentors/form.html", m=None)


# -------------------------------
# Edit (profile) – edit.html
# -------------------------------
@bp.get("/<int:mentor_id>/edit")
@login_required
def edit_form(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    taught = Course.query.filter(Course.mentor_id == m.id).order_by(Course.created_at.desc()).all()
    all_courses = Course.query.order_by(Course.created_at.desc()).all()

    # خلاصه مالی برای کارت‌های بالا
    totals = _mentor_finance_summary(m.id)["totals"]

    back_url = request.referrer or url_for("mentors.list")
    return render_template(
        "mentors/edit.html",
        m=m,
        taught=taught,
        all_courses=all_courses,
        skills_count=0,
        totals=totals,
        back_url=back_url
    )


# -------------------------------
# Update basic fields
# -------------------------------
@bp.post("/<int:mentor_id>/basic")
@login_required
def update_basic(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    f = request.form
    m.first_name = (f.get("first_name") or "").strip()
    m.last_name  = (f.get("last_name")  or "").strip()
    m.phone      = (f.get("phone")      or "").strip() or None
    m.email      = (f.get("email")      or "").strip() or None
    db.session.commit()
    flash("اطلاعات ذخیره شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))


# -------------------------------
# Upload avatar
# -------------------------------
@bp.post("/<int:mentor_id>/upload-avatar")
@login_required
def upload_avatar(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    file = request.files.get("avatar")
    if file and file.filename:
        rel = save_mentor_avatar(file, m.id)
        if rel:
            m.avatar = rel
            db.session.commit()
            flash("تصویر پروفایل به‌روزرسانی شد.", "success")
        else:
            flash("آپلود تصویر ناموفق بود.", "error")
    else:
        flash("فایلی انتخاب نشد.", "error")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))


# -------------------------------
# Assign / remove course for mentor
# -------------------------------
@bp.post("/<int:mentor_id>/courses/add")
@login_required
def add_course(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    cid = request.form.get("course_id")
    if not cid:
        flash("شناسه دوره نامعتبر است.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))
    c = Course.query.get_or_404(int(cid))
    c.mentor_id = mentor_id
    db.session.commit()
    flash("دوره به منتور نسبت داده شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))


@bp.post("/<int:mentor_id>/courses/<int:course_id>/remove")
@login_required
def remove_course(mentor_id, course_id):
    Mentor.query.get_or_404(mentor_id)
    c = Course.query.get_or_404(course_id)
    if c.mentor_id == mentor_id:
        c.mentor_id = None
        db.session.commit()
        flash("ارتباط منتور و دوره حذف شد.", "info")
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))


# -------------------------------
# Payments endpoints (AJAX)
# -------------------------------
@bp.get("/<int:mentor_id>/payments")
@login_required
def payments_list(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    payments = (
        db.session.query(MentorPayment)
        .filter(MentorPayment.mentor_id == mentor_id)
        .order_by(MentorPayment.paid_at.desc(), MentorPayment.id.desc())
        .all()
    )
    totals = _mentor_finance_summary(mentor_id)["totals"]
    items = [{
        "id": p.id,
        "amount": int(p.amount or 0),
        "kind": p.kind,
        "title": p.title or "",
        "note": p.note or "",
        "paid_at": p.paid_at.strftime("%Y-%m-%d %H:%M") if p.paid_at else "",
    } for p in payments]
    return jsonify(ok=True, items=items, totals=totals)


@bp.post("/<int:mentor_id>/payments")
@login_required
def payments_add(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    f = request.form if not request.is_json else (request.json or {})
    amount_raw = f.get("amount")
    kind   = (f.get("kind") or "EXPENSE").upper()
    title  = f.get("title")
    note   = f.get("note")

    try:
        amount = int(float(str(amount_raw).replace(",", "").replace("٬", "")))
    except Exception:
        return jsonify(ok=False, error="مبلغ نامعتبر است."), 400
    if amount <= 0:
        return jsonify(ok=False, error="مبلغ باید بیشتر از صفر باشد."), 400

    mp = MentorPayment(mentor_id=mentor_id, amount=amount, kind=kind, title=title, note=note)
    db.session.add(mp)
    db.session.commit()
    flash("پرداخت منتور ثبت شد.", "success")
    return jsonify(ok=True, id=mp.id)


@bp.delete("/<int:mentor_id>/payments/<int:pay_id>")
@login_required
def payments_delete(mentor_id, pay_id):
    Mentor.query.get_or_404(mentor_id)
    p = MentorPayment.query.filter_by(id=pay_id, mentor_id=mentor_id).first()
    if not p:
        return jsonify(ok=False, error="رکورد یافت نشد"), 404
    db.session.delete(p)
    db.session.commit()
    flash("پرداخت حذف شد.", "info")
    return jsonify(ok=True)
