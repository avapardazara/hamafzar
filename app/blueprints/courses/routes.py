from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from sqlalchemy import or_
from app.extensions import db
from app.models.course import Course

bp = Blueprint("courses", __name__, url_prefix="/courses")

# ---------- لیست دوره‌ها با جستجو و صفحه‌بندی ----------
@bp.get("/", endpoint="list")
@login_required
def list_():
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = 10

    base = Course.query
    if q:
        like = f"%{q}%"
        base = base.filter(or_(Course.title.like(like), Course.mentor_name.like(like)))

    base = base.order_by(Course.created_at.desc())
    pagination = base.paginate(page=page, per_page=per_page, error_out=False)

    return render_template("courses/index.html", q=q, pagination=pagination, items=pagination.items)

# ---------- فرم ایجاد ----------
@bp.get("/new")
@login_required
def new_form():
    return render_template("courses/form.html", course=None)

@bp.post("/new")
@login_required
def create():
    title = (request.form.get("title") or "").strip()
    mentor_name = (request.form.get("mentor_name") or "").strip()
    status = (request.form.get("status") or "ACTIVE").upper()

    if not title:
        flash("عنوان دوره الزامی است.", "error")
        return render_template("courses/form.html", course=None, form=request.form)

    c = Course(title=title, mentor_name=mentor_name or None, status=status)
    db.session.add(c)
    db.session.commit()
    flash("دوره با موفقیت ایجاد شد.", "success")
    return redirect(url_for("courses.list_"))

# ---------- فرم ویرایش ----------
@bp.get("/<int:course_id>/edit")
@login_required
def edit_form(course_id):
    c = Course.query.get_or_404(course_id)
    return render_template("courses/form.html", course=c)

@bp.post("/<int:course_id>/edit")
@login_required
def update(course_id):
    c = Course.query.get_or_404(course_id)
    title = (request.form.get("title") or "").strip()
    mentor_name = (request.form.get("mentor_name") or "").strip()
    status = (request.form.get("status") or "ACTIVE").upper()

    if not title:
        flash("عنوان دوره الزامی است.", "error")
        return render_template("courses/form.html", course=c, form=request.form)

    c.title = title
    c.mentor_name = mentor_name or None
    c.status = status
    db.session.commit()
    flash("دوره به‌روزرسانی شد.", "success")
    return redirect(url_for("courses.list_"))

# ---------- آرشیو/حذف نرم ----------
@bp.post("/<int:course_id>/archive")
@login_required
def archive(course_id):
    c = Course.query.get_or_404(course_id)
    c.status = "ARCHIVED"
    db.session.commit()
    flash("دوره بایگانی شد.", "success")
    return redirect(url_for("courses.list_"))

# ---------- حذف دائم (اختیاری) ----------
@bp.post("/<int:course_id>/delete")
@login_required
def delete(course_id):
    c = Course.query.get_or_404(course_id)
    db.session.delete(c)
    db.session.commit()
    flash("دوره حذف شد.", "success")
    return redirect(url_for("courses.list_"))
