import os
class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", None)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", None)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 📁 مسیر فایل‌های آپلودی
    UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads", "students")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # حداکثر ۲ مگابایت
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
