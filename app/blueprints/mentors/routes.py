from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app.extensions import db
from app.utils.media import save_uploaded_image
from app.models.mentor import Mentor
from app.models.course import Course

bp = Blueprint("mentors", __name__, url_prefix="/mentors")
ALLOWED_IMG = {"png", "jpg", "jpeg", "webp"}

# -------------------------------
# لیست
# -------------------------------
@bp.get("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    base = Mentor.query
    if q:
        like = f"%{q}%"
        base = base.filter(
            db.or_(
                Mentor.full_name.like(like),
                Mentor.email.like(like),
                Mentor.phone.like(like),
            )
        )
    items = base.order_by(Mentor.id.desc()).all()
    return render_template("mentors/index.html", items=items, q=q)

# -------------------------------
# شرت‌کات: دیدن پروفایل => ویرایش
# /mentors/<id> => /mentors/<id>/edit
# -------------------------------
@bp.get("/<int:mentor_id>")
@login_required
def view(mentor_id):
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))

# -------------------------------
# فرم ساخت
# -------------------------------
@bp.get("/new")
@login_required
def new_form():
    return render_template("mentors/form.html", m=None)

# -------------------------------
# ساخت
# -------------------------------
@bp.post("/new")
@login_required
def create():
    full_name = (request.form.get("full_name") or "").strip()
    email     = (request.form.get("email") or "").strip()
    phone     = (request.form.get("phone") or "").strip()

    if not full_name:
        flash("نام الزامی است.", "error")
        return redirect(url_for("mentors.new_form"))

    m = Mentor(full_name=full_name, email=email, phone=phone)

    # آپلود آواتار در لحظه‌ی ساخت (اختیاری)
    avatar_file = request.files.get("avatar")
    avatar_rel  = save_uploaded_image(avatar_file, subdir="mentors")
    if avatar_rel:
        m.avatar = avatar_rel

    db.session.add(m)
    db.session.commit()
    flash("منتور با موفقیت ایجاد شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))

# -------------------------------
# فرم ویرایش
# -------------------------------
@bp.get("/<int:mentor_id>/edit")
@login_required
def edit_form(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    return render_template("mentors/form.html", m=m)

# -------------------------------
# ذخیره‌ی ویرایش
# -------------------------------
@bp.post("/<int:mentor_id>/edit")
@login_required
def update(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    m.full_name = (request.form.get("full_name") or "").strip()
    m.email     = (request.form.get("email") or "").strip()
    m.phone     = (request.form.get("phone") or "").strip()

    avatar_file = request.files.get("avatar")
    avatar_rel  = save_uploaded_image(avatar_file, subdir="mentors")
    if avatar_rel:
        m.avatar = avatar_rel

    db.session.commit()
    flash("اطلاعات منتور به‌روزرسانی شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))

# -------------------------------
# حذف
# -------------------------------
@bp.post("/<int:mentor_id>/delete")
@login_required
def delete(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    db.session.delete(m)
    db.session.commit()
    flash("منتور حذف شد.", "info")
    return redirect(url_for("mentors.list"))

# -------------------------------
# مشخصات پایه
# -------------------------------
@bp.post("/<int:mentor_id>/update-basic")
@login_required
def update_basic(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    m.first_name = (request.form.get("first_name") or "").strip()
    m.last_name  = (request.form.get("last_name") or "").strip()
    m.phone      = (request.form.get("phone") or "").strip()
    m.email      = (request.form.get("email") or "").strip()
    m.bio        = (request.form.get("bio") or "").strip()
    db.session.commit()
    flash("مشخصات منتور ذخیره شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))

# -------------------------------
# آپلود آواتار
# -------------------------------
@bp.post("/<int:mentor_id>/avatar")
@login_required
def upload_avatar(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    f = request.files.get("avatar")
    if not f or not f.filename:
        flash("فایلی انتخاب نشده.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    avatar_rel = save_uploaded_image(f, subdir="mentors")
    if not avatar_rel:
        flash("فرمت فایل معتبر نیست.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    m.avatar = avatar_rel
    db.session.commit()
    flash("عکس پروفایل به‌روزرسانی شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))

# -------------------------------
# حذف آواتار
# -------------------------------
@bp.post("/<int:mentor_id>/avatar/delete")
@login_required
def delete_avatar(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    m.avatar = None
    db.session.commit()
    flash("عکس پروفایل حذف شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))

# -------------------------------
# نسبت دادن دوره
# -------------------------------
@bp.post("/<int:mentor_id>/courses/add")
@login_required
def add_course(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    cid = request.form.get("course_id")
    if not cid:
        flash("دوره‌ای انتخاب نشد.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    c = Course.query.get(int(cid))
    if not c:
        flash("دوره نامعتبر است.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    c.mentor_id = m.id
    db.session.commit()
    flash("دوره به منتور منتسب شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))

# -------------------------------
# حذف نسبت دوره
# -------------------------------
@bp.post("/<int:mentor_id>/courses/<int:course_id>/delete")
@login_required
def remove_course(mentor_id, course_id):
    m = Mentor.query.get_or_404(mentor_id)
    c = Course.query.get_or_404(course_id)
    if c.mentor_id == m.id:
        c.mentor_id = None
        db.session.commit()
        flash("دوره از منتور جدا شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))
# ---- [BEGIN mentor payments API] -------------------------------------------
from datetime import datetime
from flask import request
from sqlalchemy import func, case
from app.extensions import db
from app.models.payment import Payment
from app.models.mentor import Mentor

def _to_int(x):
    s = str(x or "0").replace(",", "").replace("٬", "").strip()
    try:
        return int(float(s))
    except Exception:
        return 0

def _parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v)
    except Exception:
        return None

@bp.route("/<int:mentor_id>/payments", methods=["GET"])
def api_list_payments(mentor_id):
    Mentor.query.get_or_404(mentor_id)

    q = Payment.query.filter_by(mentor_id=mentor_id).order_by(
        Payment.paid_at.desc().nullslast(), Payment.id.desc()
    )
    items = [{
        "id": p.id,
        "mentor_id": p.mentor_id,
        "amount": int(p.amount or 0),
        "kind": p.kind,
        "status": p.status,
        "paid_at": p.paid_at.isoformat() if p.paid_at else None,
        "note": p.note,
        "title": p.title,
        "type": p.type,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in q.all()]

    income = func.coalesce(func.sum(case((Payment.kind == "INCOME", Payment.amount), else_=0)), 0)
    expense = func.coalesce(func.sum(case((Payment.kind == "EXPENSE", Payment.amount), else_=0)), 0)
    s = db.session.query(income.label("income"), expense.label("expense"))\
                  .filter(Payment.mentor_id == mentor_id).one()
    totals = {
        "income": int(s.income or 0),
        "expense": int(s.expense or 0),
        "balance": int((s.income or 0) - (s.expense or 0))
    }
    return {"ok": True, "items": items, "totals": totals}

@bp.route("/<int:mentor_id>/payments", methods=["POST"])
def api_add_payment(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    data = (request.get_json(silent=True) or request.form)

    kind = (data.get("kind") or "EXPENSE").upper()   # INCOME | EXPENSE
    if kind not in ("INCOME", "EXPENSE"):
        return {"ok": False, "error": "kind must be INCOME or EXPENSE"}, 400

    status = (data.get("status") or "PAID").upper()  # PAID | DUE
    if status not in ("PAID", "DUE"):
        return {"ok": False, "error": "status must be PAID or DUE"}, 400

    p = Payment(
        mentor_id=mentor_id,
        student_id=None,
        kind=kind,
        status=status,
        type=("OUT" if kind == "EXPENSE" else "IN"),
        amount=_to_int(data.get("amount")),
        title=data.get("title"),
        note=data.get("note"),
        paid_at=_parse_dt(data.get("paid_at")),
    )
    db.session.add(p)
    db.session.commit()
    return {"ok": True, "id": p.id}

@bp.route("/<int:mentor_id>/payments/<int:pay_id>", methods=["DELETE"])
def api_delete_payment(mentor_id, pay_id):
    Mentor.query.get_or_404(mentor_id)
    p = Payment.query.filter_by(id=pay_id, mentor_id=mentor_id).first_or_404()
    db.session.delete(p)
    db.session.commit()
    return {"ok": True}
# ---- [END mentor payments API] ---------------------------------------------
