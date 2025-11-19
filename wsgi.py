from flask import send_from_directory,  current_app   # ✅ این خط باعث رفع خطا می‌شود
from app import create_app
import os

app = create_app()

# 📁 سرو فایل‌های آپلودی (مثل تصاویر دانشجو)
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # اینجا دقیقاً باید با _uploads_root در files.py یکی باشه
    uploads_root = os.path.join(os.getcwd(), "uploads")
    return send_from_directory(uploads_root, filename)
