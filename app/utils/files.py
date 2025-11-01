# app/utils/files.py
import os
from werkzeug.utils import secure_filename
from flask import current_app

# -----------------------------
# مشترک‌ها
# -----------------------------
def allowed_file(filename: str):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def _uploads_root():
    # ریشه‌ی فولدر عمومی uploads (برای ساخت rel_path)
    return os.path.join(os.getcwd(), "uploads")

# -----------------------------
# دانشجو (بدون تغییر)
# -----------------------------
def save_student_avatar(file_storage, student_id):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None

    # فایل نهایی در uploads/students/ (فرض: UPLOAD_FOLDER برای دانشجو تنظیم شده)
    filename = secure_filename(f"student_{student_id}.jpg")
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    _ensure_dir(upload_dir)

    # مسیر کامل ذخیره روی دیسک
    abs_path = os.path.join(upload_dir, filename)
    file_storage.save(abs_path)

    # مسیر نسبی برای ذخیره در DB (که در /uploads/... نمایش داده بشه)
    rel_path = os.path.relpath(abs_path, _uploads_root()).replace("\\", "/")
    return rel_path

def delete_student_avatar(student):
    if not getattr(student, "avatar_path", None):
        return
    abs_path = os.path.join(_uploads_root(), student.avatar_path)
    if os.path.exists(abs_path):
        os.remove(abs_path)

# -----------------------------
# منتور (جدید، هم‌ساخت با دانشجو)
# -----------------------------
def save_mentor_avatar(file_storage, mentor_id):
    """
    ذخیره‌ی آواتار منتور با نام ثابت و مسیر نسبی.
    اگر در config کلید MENTOR_UPLOAD_FOLDER باشد، همان استفاده می‌شود؛
    وگرنه بصورت پیش‌فرض uploads/mentors را در نظر می‌گیرد.
    """
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None

    filename = secure_filename(f"mentor_{mentor_id}.jpg")

    # اولویت: config → پیش‌فرض
    upload_dir = current_app.config.get("MENTOR_UPLOAD_FOLDER") or os.path.join(_uploads_root(), "mentors")
    _ensure_dir(upload_dir)

    abs_path = os.path.join(upload_dir, filename)
    file_storage.save(abs_path)

    rel_path = os.path.relpath(abs_path, _uploads_root()).replace("\\", "/")
    return rel_path

def delete_mentor_avatar(mentor):
    """
    حذف فایل آواتار منتور براساس mentor.avatar_path (مسیر نسبی).
    """
    avatar_path = getattr(mentor, "avatar_path", None)
    if not avatar_path:
        return
    abs_path = os.path.join(_uploads_root(), avatar_path)
    if os.path.exists(abs_path):
        os.remove(abs_path)

# -----------------------------
# دوره (جدید، هم‌ساخت با دانشجو)
# -----------------------------
def save_course_cover(file_storage, course_id):
    """
    ذخیره‌ی کاور دوره با نام ثابت و مسیر نسبی.
    اگر در config کلید COURSE_UPLOAD_FOLDER باشد، همان استفاده می‌شود؛
    وگرنه بصورت پیش‌فرض uploads/courses را در نظر می‌گیرد.
    """
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None

    filename = secure_filename(f"course_{course_id}_cover.jpg")

    upload_dir = current_app.config.get("COURSE_UPLOAD_FOLDER") or os.path.join(_uploads_root(), "courses")
    _ensure_dir(upload_dir)

    abs_path = os.path.join(upload_dir, filename)
    file_storage.save(abs_path)

    rel_path = os.path.relpath(abs_path, _uploads_root()).replace("\\", "/")
    return rel_path

def delete_course_cover(course):
    """
    حذف فایل کاور دوره براساس course.cover_image یا course.cover_path (هرکدام موجود بود).
    """
    rel = getattr(course, "cover_image", None) or getattr(course, "cover_path", None)
    if not rel:
        return
    abs_path = os.path.join(_uploads_root(), rel)
    if os.path.exists(abs_path):
        os.remove(abs_path)
