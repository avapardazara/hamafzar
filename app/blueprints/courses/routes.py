# app/blueprints/courses/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import or_
from datetime import datetime
from app.extensions import db
from app.models.course import Course
from app.models.mentor import Mentor
from app.utils.media import save_uploaded_image

bp = Blueprint("courses", __name__, url_prefix="/courses")

# ---------- لیست ----------
@bp.get("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    page = int(request.args.get("page") or 1)
    per_page = 12

    base = Course.query
    if q:
        like = f"%{q}%"
        base = base.filter(or_(Course.title.like(like), Course.mentor_name.like(like)))

    pagination = base.order_by(Course.id.desc()).paginate(page=page, per_page=per_page)
    items = pagination.items
    return render_template("courses/index.html", items=items, pagination=pagination, q=q)

# ---------- ساخت ----------
@bp.get("/new")
@login_required
def new_form():
    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    return render_template("courses/form.html", c=None, mentors=mentors, mode="create")

@bp.post("/new")
@login_required
def create():
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("نام دوره الزامی است.", "error")
        return redirect(url_for("courses.new_form"))

    c = Course(
        title=title,
        description=(request.form.get("description") or "").strip() or None,
        mentor_id=(int(request.form.get("mentor_id")) if request.form.get("mentor_id") else None),
        start_date=_parse_date(request.form.get("start_date")),
        end_date=_parse_date(request.form.get("end_date")),
        schedule_type=(request.form.get("schedule_type") or "CUSTOM"),
        fee_per_student=_to_int(request.form.get("fee_per_student")),
        installment_enabled=(request.form.get("installment_enabled") == "1"),
        mentor_share_percent=_to_float(request.form.get("mentor_share_percent")),
        status=(request.form.get("status") or "ACTIVE"),
    )

    # کشِ نام منتور برای لیست‌ها (اختیاری)
    if c.mentor_id:
        m = Mentor.query.get(c.mentor_id)
        c.mentor_name = (m.full_name or (f"{m.first_name or ''} {m.last_name or ''}".strip())) if m else None

    # JSONهای زمان‌بندی/اقساط
    c.sessions_json = _safe_json(request.form.get("sessions_json")) or None
    c.weekly_days_json = _safe_json(request.form.get("weekly_days_json")) or None
    c.pair_odd = (request.form.get("pair_odd") or None)
    c.installments_json = _safe_json(request.form.get("installments_json")) or None

    # تصویر
    cover_file = request.files.get("cover_image")
    cover_rel = save_uploaded_image(cover_file, subdir="courses")
    if cover_rel:
        c.cover_image = cover_rel

    db.session.add(c)
    db.session.commit()
    flash("دوره با موفقیت ایجاد شد.", "success")
    return redirect(url_for("courses.edit_form", course_id=c.id))

# ---------- ویرایش ----------
@bp.get("/<int:course_id>/edit")
@login_required
def edit_form(course_id):
    c = Course.query.get_or_404(course_id)
    mentors = Mentor.query.order_by(Mentor.id.desc()).all()
    return render_template("courses/form.html", c=c, mentors=mentors, mode="edit")

@bp.post("/<int:course_id>/edit")
@login_required
def update(course_id):
    c = Course.query.get_or_404(course_id)
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("نام دوره الزامی است.", "error")
        return redirect(url_for("courses.edit_form", course_id=c.id))

    c.title = title
    c.description = (request.form.get("description") or "").strip() or None
    c.mentor_id = (int(request.form.get("mentor_id")) if request.form.get("mentor_id") else None)
    c.start_date = _parse_date(request.form.get("start_date"))
    c.end_date = _parse_date(request.form.get("end_date"))
    c.schedule_type = (request.form.get("schedule_type") or "CUSTOM")
    c.fee_per_student = _to_int(request.form.get("fee_per_student"))
    c.installment_enabled = (request.form.get("installment_enabled") == "1")
    c.mentor_share_percent = _to_float(request.form.get("mentor_share_percent"))
    c.status = (request.form.get("status") or "ACTIVE")

    # کشِ نام منتور
    c.mentor_name = None
    if c.mentor_id:
        m = Mentor.query.get(c.mentor_id)
        c.mentor_name = (m.full_name or (f"{m.first_name or ''} {m.last_name or ''}".strip())) if m else None

    # JSONها
    c.sessions_json = _safe_json(request.form.get("sessions_json")) or None
    c.weekly_days_json = _safe_json(request.form.get("weekly_days_json")) or None
    c.pair_odd = (request.form.get("pair_odd") or None)
    c.installments_json = _safe_json(request.form.get("installments_json")) or None

    # تصویر
    cover_file = request.files.get("cover_image")
    if cover_file and getattr(cover_file, "filename", ""):
        cover_rel = save_uploaded_image(cover_file, subdir="courses")
        if cover_rel:
            c.cover_image = cover_rel

    db.session.commit()
    flash("دوره به‌روزرسانی شد.", "success")
    return redirect(url_for("courses.edit_form", course_id=c.id))

# ---------- بایگانی/حذف (اختیاری مطابق لیست فعلی) ----------
@bp.post("/<int:course_id>/archive")
@login_required
def archive(course_id):
    c = Course.query.get_or_404(course_id)
    c.status = "ARCHIVED"
    db.session.commit()
    flash("دوره بایگانی شد.", "info")
    return redirect(url_for("courses.list"))

@bp.post("/<int:course_id>/delete")
@login_required
def delete(course_id):
    c = Course.query.get_or_404(course_id)
    db.session.delete(c)
    db.session.commit()
    flash("دوره حذف شد.", "info")
    return redirect(url_for("courses.list"))

# ---------- helpers ----------
def _to_int(x):
    try:
        s = str(x or "0").replace(",", "").replace("٬", "").strip()
        return int(float(s))
    except Exception:
        return 0

def _to_float(x):
    try:
        s = str(x or "0").replace(",", "").replace("٬", "").strip()
        return float(s)
    except Exception:
        return None

def _parse_date(s):
    if not s: return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _safe_json(s):
    if not s: return None
    import json
    try:
        return json.loads(s)
    except Exception:
        return None
