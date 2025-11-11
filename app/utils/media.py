# app/utils/media.py
import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app

ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp","pdf","doc"}
ALLOWED_ALL = None

def _uploads_root():
    return os.path.join(current_app.instance_path, "uploads")

def _ext_of(fname: str) -> str:
    if not fname or "." not in fname:
        return ""
    return fname.rsplit(".", 1)[-1].lower()

def save_uploaded_image(file_storage, subdir: str = "", old_path: str | None = None) -> str | None:
    """
    ذخیره ایمن فایل تصویر.
    - برای جلوگیری از برخورد نام: <uuid>.<ext>
    - در صورت ارسال old_path، فایل قبلی حذف می‌شود.
    خروجی: مسیر نسبی از ریشه uploads، مثل: 'mentors/1f2a...c9a.jpg'
    """
    if not file_storage or not getattr(file_storage, "filename", ""):
        return old_path  # اگر فایلی نیامده، همان قبلی را برگردان

    ext = _ext_of(file_storage.filename)
    if ext not in ALLOWED_EXT:
        return old_path

    # ساخت نام امن و یکتا
    name = f"{uuid.uuid4().hex}.{ext}"
    if subdir:
        rel_path = f"{subdir}/{name}"
        folder = os.path.join(_uploads_root(), subdir)
    else:
        rel_path = name
        folder = _uploads_root()

    os.makedirs(folder, exist_ok=True)
    abs_path = os.path.join(folder, name)
    file_storage.save(abs_path)

    # حذف فایل قدیمی (اگر مسیر قبلی داده شده بود و فرق دارد)
    if old_path and old_path != rel_path:
        remove_media(old_path)

    return rel_path

def remove_media(rel_path: str | None):
    """حذف فایل قدیمی اگر وجود داشته باشد (مسیر نسبی از /uploads)."""
    if not rel_path:
        return
    try:
        abs_path = os.path.join(_uploads_root(), rel_path)
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except Exception:
        pass
def save_uploaded_file(file_storage, *, subdir="sessions", allowed_exts=ALLOWED_ALL):
    """
    فایل را زیر instance/uploads/<subdir>/ ذخیره می‌کند.
    خروجی: مسیر relative برای ذخیره در DB مثل: 'uploads/sessions/123/my.pdf'
    """
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None

    fname = secure_filename(file_storage.filename)
    if not fname:
        return None

    # اگر بخواهی محدودیت پسوند بگذاری:
    if allowed_exts is not None:
        ext = os.path.splitext(fname)[1].lower().lstrip(".")
        if ext not in allowed_exts:
            return None

    root = os.path.join(current_app.instance_path, "uploads", subdir)
    os.makedirs(root, exist_ok=True)
    abs_path = os.path.join(root, fname)

    # اگر فایل همنام وجود داشت، suffix عددی اضافه کن
    base, ext = os.path.splitext(fname)
    i = 1
    while os.path.exists(abs_path):
        fname = f"{base}_{i}{ext}"
        abs_path = os.path.join(root, fname)
        i += 1

    file_storage.save(abs_path)

    # مسیر relative که بعداً با send_from_directory سرو می‌کنیم
    rel = os.path.join("uploads", subdir, fname).replace("\\", "/")
    return rel