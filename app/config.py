import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-env")

    # مسیر مطلق با اسلش رو به جلو (سازگار با sqlite روی ویندوز)
    _instance_dir = os.path.join(os.path.dirname(BASE_DIR), "instance")
    os.makedirs(_instance_dir, exist_ok=True)
    _db_path = os.path.join(_instance_dir, "app.db")
    _db_uri = "sqlite:///" + _db_path.replace("\\", "/")

    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", _db_uri)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRES", "3600"))
