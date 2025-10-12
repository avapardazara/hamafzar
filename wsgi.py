from flask import send_from_directory,  current_app   # ✅ این خط باعث رفع خطا می‌شود
from app import create_app
import os

app = create_app()

# 📁 سرو فایل‌های آپلودی (مثل تصاویر دانشجو)
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    upload_root = os.path.join(current_app.root_path, "..", "uploads")
    return send_from_directory(upload_root, filename)
