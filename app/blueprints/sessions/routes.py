# app/blueprints/sessions/routes.py
from __future__ import annotations
import os
from datetime import datetime
from typing import Optional

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, current_app
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db
from app.utils.decorators import role_required
from app.models.course import Course
from app.models.course_session import CourseSession
# اگر مدل فایل جلسه جدا داری:
# from app.models.session_file import SessionFile
# اگر نداری موقتاً این کلاس ساده را تعریف کن یا از مدل موجودت استفاده کن.
from sqlalchemy import text

bp = Blueprint("sessions", __name__, url_prefix="/sessions")


# ---------- Helpers ----------
def _can_manage_course(course: Course) -> bool:
    if not course:
        return False
    if getattr(current_user, "role", None) == "admin":
        return True
    return getattr(current_user, "id", None) == getattr(course, "mentor_id", None)


def _parse_dt_local(val: Optional[str]) -> Optional[datetime]:
    """
    ورودی از input[type=datetime-local] مثل 2025-11-08T10:30
    """
    if not val:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            pass
    return None


def _upload_root() -> str:
    root = current_app.config.get("UPLOAD_FOLDER")
    if not root:
        # fallback امن داخل instance
        root = os.path.join(current_app.instance_path, "uploads")
    os.makedirs(root, exist_ok=True)
    return root


# ---------- List sessions of a course ----------
@bp.get("/of-course/<int:course_id>")
@login_required
def list_by_course(course_id: int):
    course = Course.query.get_or_404(course_id)
    items = (
        CourseSession.query
        .filter_by(course_id=course.id)
        .order_by(CourseSession.date.desc())
        .all()
    )
    can_manage = _can_manage_course(course)
    return render_template(
        "sessions/list.html",
        course=course, items=items, can_manage=can_manage
    )


# ---------- New / Create ----------
@bp.get("/new/<int:course_id>")
@login_required
@role_required(["MENTOR", "admin"])
def new(course_id: int):
    course = Course.query.get_or_404(course_id)
    if not _can_manage_course(course):
        flash("شما اجازه افزودن جلسه برای این دوره را ندارید.", "error")
        return redirect(url_for("sessions.list_by_course", course_id=course.id))

    return render_template(
        "sessions/form.html",
        course=course,
        form_action=url_for("sessions.create", course_id=course.id)
    )


@bp.post("/create/<int:course_id>")
@login_required
@role_required(["MENTOR", "admin"])
def create(course_id: int):
    course = Course.query.get_or_404(course_id)
    if not _can_manage_course(course):
        flash("شما اجازه افزودن جلسه برای این دوره را ندارید.", "error")
        return redirect(url_for("sessions.list_by_course", course_id=course.id))

    topic = (request.form.get("topic") or "").strip()
    description = (request.form.get("description") or "").strip()
    date_val = _parse_dt_local(request.form.get("date"))

    if not topic:
        flash("موضوع جلسه الزامی است.", "error")
        return redirect(url_for("sessions.new", course_id=course.id))
    if not date_val:
        flash("تاریخ/ساعت جلسه نامعتبر است.", "error")
        return redirect(url_for("sessions.new", course_id=course.id))

    s = CourseSession(
        course_id=course.id,
        mentor_id=getattr(current_user, "id", None),
        topic=topic,
        description=description or None,
        date=date_val,
    )
    db.session.add(s)
    db.session.commit()
    flash("جلسه با موفقیت ثبت شد.", "success")
    return redirect(url_for("sessions.view", session_id=s.id))


# ---------- View ----------
@bp.get("/<int:session_id>")
@login_required
def view(session_id: int):
    s = CourseSession.query.get_or_404(session_id)
    course = Course.query.get_or_404(s.course_id)
    can_manage = _can_manage_course(course)

    # اگر relation فایل داری، از s.files استفاده کن؛ در غیر این صورت کوئری بزن
    try:
        files = getattr(s, "files", None)
    except Exception:
        files = None

    return render_template(
        "sessions/view.html",
        s=s, course=course, files=files, can_manage=can_manage
    )


# ---------- Edit / Update ----------
@bp.get("/<int:session_id>/edit")
@login_required
@role_required(["MENTOR", "admin"])
def edit(session_id: int):
    s = CourseSession.query.get_or_404(session_id)
    course = Course.query.get_or_404(s.course_id)
    if not _can_manage_course(course):
        flash("شما اجازه ویرایش این جلسه را ندارید.", "error")
        return redirect(url_for("sessions.view", session_id=s.id))

    return render_template(
        "sessions/form.html",
        s=s, course=course,
        form_action=url_for("sessions.update", session_id=s.id)
    )


@bp.post("/<int:session_id>/update")
@login_required
@role_required(["MENTOR", "admin"])
def update(session_id: int):
    s = CourseSession.query.get_or_404(session_id)
    course = Course.query.get_or_404(s.course_id)
    if not _can_manage_course(course):
        flash("شما اجازه ویرایش این جلسه را ندارید.", "error")
        return redirect(url_for("sessions.view", session_id=s.id))

    topic = (request.form.get("topic") or "").strip()
    description = (request.form.get("description") or "").strip()
    date_val = _parse_dt_local(request.form.get("date"))

    if not topic:
        flash("موضوع جلسه الزامی است.", "error")
        return redirect(url_for("sessions.edit", session_id=s.id))
    if not date_val:
        flash("تاریخ/ساعت جلسه نامعتبر است.", "error")
        return redirect(url_for("sessions.edit", session_id=s.id))

    s.topic = topic
    s.description = description or None
    s.date = date_val
    db.session.commit()

    flash("تغییرات جلسه ذخیره شد.", "success")
    return redirect(url_for("sessions.view", session_id=s.id))


# ---------- Delete ----------
@bp.post("/<int:session_id>/delete")
@login_required
@role_required(["MENTOR", "admin"])
def delete(session_id: int):
    s = CourseSession.query.get_or_404(session_id)
    course = Course.query.get_or_404(s.course_id)
    if not _can_manage_course(course):
        flash("شما اجازه حذف این جلسه را ندارید.", "error")
        return redirect(url_for("sessions.view", session_id=s.id))

    db.session.delete(s)
    db.session.commit()
    flash("جلسه حذف شد.", "success")
    return redirect(url_for("sessions.list_by_course", course_id=course.id))


# ---------- Upload file ----------
@bp.post("/<int:session_id>/files")
@login_required
@role_required(["MENTOR", "admin"])
def upload_file(session_id: int):
    s = CourseSession.query.get_or_404(session_id)
    course = Course.query.get_or_404(s.course_id)
    if not _can_manage_course(course):
        flash("شما اجازه آپلود فایل برای این جلسه را ندارید.", "error")
        return redirect(url_for("sessions.view", session_id=s.id))

    f = request.files.get("file")
    desc = (request.form.get("description") or "").strip()
    if not f or not f.filename:
        flash("فایلی انتخاب نشده است.", "error")
        return redirect(url_for("sessions.view", session_id=s.id))

    filename = secure_filename(f.filename)
    root = _upload_root()
    save_path = os.path.join(root, filename)
    f.save(save_path)

    # اگر SessionFile مدل مستقل داری:
    # sf = SessionFile(session_id=s.id, file_path=filename, description=desc or None)
    # db.session.add(sf)
    # db.session.commit()

    flash("فایل با موفقیت آپلود شد.", "success")
    return redirect(url_for("sessions.view", session_id=s.id))


# ---------- Delete file ----------
@bp.post("/files/<int:file_id>/delete")
@login_required
@role_required(["MENTOR", "admin"])
def delete_file(file_id: int):
    # اگر SessionFile داری:
    # sf = SessionFile.query.get_or_404(file_id)
    # s = CourseSession.query.get_or_404(sf.session_id)
    # course = Course.query.get_or_404(s.course_id)
    # if not _can_manage_course(course):
    #     flash("شما اجازه حذف این فایل را ندارید.", "error")
    #     return redirect(url_for("sessions.view", session_id=s.id))
    # db.session.delete(sf); db.session.commit()
    # flash("فایل حذف شد.", "success")
    # return redirect(url_for("sessions.view", session_id=s.id))
    flash("حذف فایل هنوز پیاده‌سازی نشده (نیازمند SessionFile).", "error")
    return redirect(request.referrer or url_for("dashboard.index"))
