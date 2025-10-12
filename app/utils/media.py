import os, uuid
from werkzeug.utils import secure_filename
from flask import current_app

ALLOWED_IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

def save_uploaded_image(file_storage, subdir="profiles"):
    """
    file_storage: request.files['avatar'] مثلا
    برمی‌گرداند: relative_name برای ذخیره در DB (مثال: profiles/ab12cd.jpg)
    """
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMG_EXT:
        return None

    rel_dir = os.path.join(subdir)
    abs_dir = os.path.join(current_app.config["UPLOAD_DIR"], rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    new_name = f"{uuid.uuid4().hex}.{ext}"
    rel_path = os.path.join(rel_dir, new_name)
    abs_path = os.path.join(current_app.config["UPLOAD_DIR"], rel_path)

    file_storage.save(abs_path)
    return rel_path.replace("\\", "/")
