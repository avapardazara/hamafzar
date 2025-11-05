import os
from flask import Flask, url_for
from .config import Config
from .extensions import init_app as init_extensions
from .blueprints.files import bp as files_bp
from .blueprints import  finance_bp 
from app.blueprints.api import api_bp
from app.cli import register_cli

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.register_blueprint(files_bp)
    app.config.from_object(config_class)
    app.register_blueprint(finance_bp)
    app.config.from_pyfile("config.py", silent=True)
    app.register_blueprint(api_bp)
    register_cli(app)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    # اطمینان از وجود پوشه‌ی instance
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.setdefault("UPLOAD_DIR", os.path.join(os.getcwd(), "uploads"))
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    # فیلتر Jinja برای URL عکس پروفایل
    def avatar_url(filename):
        if filename:
            return url_for("uploaded_file", filename=filename)
        return url_for("static", filename="images/avatar-default.png")
    app.jinja_env.filters["avatar_url"] = avatar_url

    # 🚨 مسیر DB را "بدون شرط" به instance/app.db ست کن (مطلق)
    db_path = os.path.join(app.instance_path, "app.db").replace("\\", "/")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    init_extensions(app)

    from .blueprints import blueprints
    for bp in blueprints:
        if bp.name in app.blueprints:
            continue
        app.register_blueprint(bp)

    return app
