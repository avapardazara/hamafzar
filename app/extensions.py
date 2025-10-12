from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login_form"  # اگر کاربر لاگین نباشه، هدایت می‌شه به این

def init_app(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
