from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from app.extensions import db
from app.utils.media import save_uploaded_image
from app.models.mentor import Mentor
from app.models.course import Course
from datetime import datetime
from sqlalchemy import func, case
from app.models.payment import Payment
from pathlib import Path
from werkzeug.utils import secure_filename
from app.models.skill import Skill
from app.models.mentor_skill import MentorSkill

ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}

def _is_allowed_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTS

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
                Mentor.first_name.like(like),
                Mentor.last_name.like(like),
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
@bp.get("/<int:mentor_id>/form")
@login_required
def edit_form_page(mentor_id):
    """نمایش فرم ویرایش با مقادیر پرشده"""
    m = Mentor.query.get_or_404(mentor_id)
    return render_template("mentors/form.html", m=m)

# -------------------------------
# ساخت
# -------------------------------
@bp.post("/new")
@login_required
def create():
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    email     = (request.form.get("email") or "").strip()
    phone     = (request.form.get("phone") or "").strip()

    if not first_name:
        flash("نام الزامی است.", "error")
        return redirect(url_for("mentors.new_form"))

    m = Mentor(first_name=first_name,last_name=last_name, email=email, phone=phone)

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
    # داده‌های لازم برای تب «دوره‌ها»
    taught = Course.query.filter_by(mentor_id=m.id).order_by(Course.id.desc()).all()
    all_courses = Course.query.order_by(Course.title.asc()).all()
    # این‌جا حتماً edit.html را رندر کن (نه form.html)
    return render_template("mentors/edit.html", m=m, taught=taught, all_courses=all_courses)

# -------------------------------
# ذخیره‌ی ویرایش
# -------------------------------
@bp.post("/<int:mentor_id>/edit")
@login_required
def update(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    m.first_name = (request.form.get("first_name") or "").strip()
    m.last_name = (request.form.get("last_name") or "").strip()
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
    m.first_name = request.form.get("first_name") or m.first_name
    m.last_name  = request.form.get("last_name")  or m.last_name
    m.email      = request.form.get("email")      or m.email
    m.phone      = request.form.get("phone")      or m.phone
    
    fn = (m.first_name or "").strip()
    ln = (m.last_name or "").strip()
    m.full_name = (f"{fn} {ln}").strip() or None

    db.session.commit()
    flash("مشخصات منتور ذخیره شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))

# -------------------------------
# آپلود آواتار
# -------------------------------
@bp.route("/<int:mentor_id>/avatar", methods=["POST"])
def upload_avatar(mentor_id):
    mentor = Mentor.query.get_or_404(mentor_id)

    file = request.files.get("avatar")
    if not file or file.filename == "":
        flash("فایلی انتخاب نشده است.", "warning")
        return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))

    if not _is_allowed_image(file.filename):
        flash("فرمت تصویر معتبر نیست. فرمت‌های مجاز: png, jpg, jpeg, webp, gif", "danger")
        return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))

    # مسیر ذخیره‌سازی: uploads/avatars/mentors/<id>/
    upload_root = Path(current_app.root_path).parent / "uploads"
    target_dir = upload_root / "avatars" / "mentors" / str(mentor_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    # نام امن + افزودن timestamp برای یکتا بودن
    stem = Path(secure_filename(file.filename)).stem
    ext = Path(file.filename).suffix.lower()
    from datetime import datetime
    new_name = f"{stem}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"
    abs_path = target_dir / new_name

    file.save(str(abs_path))

    # مسیر نسبی‌ای که با files.uploaded_file سرو می‌شه:
    rel_path = str(abs_path.relative_to(upload_root)).replace("\\", "/")
    mentor.avatar = rel_path
    db.session.commit()

    flash("تصویر پروفایل با موفقیت به‌روزرسانی شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))
# -------------------------------
# حذف آواتار
# -------------------------------
@bp.route("/<int:mentor_id>/avatar/delete", methods=["POST"])
def delete_avatar(mentor_id):
    mentor = Mentor.query.get_or_404(mentor_id)
    if mentor.avatar:
        # تلاش برای حذف فایل (اختیاری؛ اگر نبود اشکالی ندارد)
        try:
            upload_root = Path(current_app.root_path).parent / "uploads"
            p = upload_root / mentor.avatar
            if p.is_file():
                p.unlink()
        except Exception:
            pass
        mentor.avatar = None
        db.session.commit()
        flash("تصویر پروفایل حذف شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))

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
def _get_or_create_skill(name: str, typ: str) -> Skill | None:
    if not name:
        return None
    name = name.strip()
    typ = (typ or "").strip().upper()  # 'TECH' | 'SOFT'
    if typ not in ("TECH", "SOFT"):
        return None
    s = Skill.query.filter_by(name=name, type=typ).first()
    if s:
        return s
    s = Skill(name=name, type=typ)
    db.session.add(s)
    db.session.flush()  # id بگیریم قبل از commit
    return s

@bp.get("/<int:mentor_id>/skills")
@login_required
def api_list_skills(mentor_id):
    Mentor.query.get_or_404(mentor_id)

    rows = (db.session.query(MentorSkill)
            .filter(MentorSkill.mentor_id == mentor_id)
            .order_by(MentorSkill.id.desc())
            .all())
    tech, soft = [], []
    for r in rows:
        item = {
            "id": r.id,
            "title": r.skill.name if r.skill else "",
            "type": r.skill.type if r.skill else "",
            "date_label": r.date_label,
            "hours": r.hours,
        }
        if r.skill and r.skill.type == "TECH":
            tech.append(item)
        else:
            soft.append(item)
    return {"ok": True, "tech": tech, "soft": soft}

@bp.post("/<int:mentor_id>/skills")
@login_required
def api_add_skill(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    data = request.get_json(silent=True) or request.form

    name = (data.get("name") or "").strip()
    typ  = (data.get("type") or "").strip().upper()  # 'TECH' | 'SOFT'
    if not name or typ not in ("TECH", "SOFT"):
        return {"ok": False, "error": "name/type invalid"}, 400

    skill = _get_or_create_skill(name, typ)
    if not skill:
        return {"ok": False, "error": "invalid skill"}, 400

    ms = MentorSkill(
        mentor_id=mentor_id,
        skill_id=skill.id,
        date_label=(data.get("date_label") or "").strip() or None,
        hours=int((data.get("hours") or 0) or 0) if typ == "SOFT" else None,
    )
    db.session.add(ms)
    db.session.commit()
    return {"ok": True, "id": ms.id}

@bp.delete("/<int:mentor_id>/skills/<int:ms_id>")
@login_required
def api_delete_skill(mentor_id, ms_id):
    Mentor.query.get_or_404(mentor_id)
    ms = MentorSkill.query.filter_by(id=ms_id, mentor_id=mentor_id).first_or_404()
    db.session.delete(ms)
    db.session.commit()
    return {"ok": True}