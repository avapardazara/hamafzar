import os
from werkzeug.utils import secure_filename
from flask import current_app

def allowed_file(filename: str):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]

def save_student_avatar(file_storage, student_id):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None

    # فایل نهایی در uploads/students/
    filename = secure_filename(f"student_{student_id}.jpg")
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)

    # مسیر کامل ذخیره روی دیسک
    abs_path = os.path.join(upload_dir, filename)
    file_storage.save(abs_path)

    # مسیر نسبی برای ذخیره در DB (که در /uploads/... نمایش داده بشه)
    rel_path = os.path.relpath(abs_path, os.path.join(os.getcwd(), "uploads")).replace("\\", "/")
    return rel_path

def delete_student_avatar(student):
    if not student.avatar_path:
        return
    abs_path = os.path.join(os.getcwd(), "uploads", student.avatar_path)
    if os.path.exists(abs_path):
        os.remove(abs_path)
