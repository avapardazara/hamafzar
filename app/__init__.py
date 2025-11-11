from flask import Flask
from .extensions import init_extensions, db, jwt
from .config import Config  # اگر دارید
from .models.user import User
# ...

def create_app(config_class: type = Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    init_extensions(app)

    # ثبت بلوپرینت‌های قبلی شما ...
    from .blueprints.api import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    # ثبت Auth API
    from .blueprints.api_auth import api_auth_bp
    app.register_blueprint(api_auth_bp, url_prefix="/api/auth")

    # JWT تنظیمات پایه (اگر در Config نبود)
    app.config.setdefault("JWT_SECRET_KEY", app.config.get("SECRET_KEY", "change-me"))
    app.config.setdefault("JWT_ACCESS_TOKEN_EXPIRES", 60 * 60)  # 1h

    # نمونه هندلر خطای JWT (اختیاری)
    @jwt.invalid_token_loader
    def invalid_token(reason):
        return {"message": "Invalid token", "reason": reason}, 401

    return app
@app.cli.command("create-user")
def create_user():
    """Flask CLI: ایجاد کاربر تست"""
    import getpass
    username = input("username: ").strip()
    full_name = input("full name (optional): ").strip()
    password = getpass.getpass("password: ")
    if not username or not password:
        print("username & password required"); return
    if User.query.filter_by(username=username).first():
        print("User exists"); return
    u = User(username=username, full_name=full_name)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    print(f"User {username} created.")