# app/__init__.py
import os
from flask import Flask, send_from_directory,current_app
from flask_cors import CORS

from .config import Config
from .extensions import init_extensions, db, jwt, login_manager
from .blueprints.auth.routes import bp as auth_bp


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # --- تنظیم SQLite با مسیر مطلق (سازگار با ویندوز) ---
    os.makedirs(app.instance_path, exist_ok=True)
    db_path = os.path.join(app.instance_path, "app.db")
    db_uri = "sqlite:///" + db_path.replace("\\", "/")
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri
    app.config.setdefault(
        "SQLALCHEMY_ENGINE_OPTIONS",
        {"connect_args": {"check_same_thread": False}},
    )

    print(f"[DB] instance_path = {app.instance_path}")
    print(f"[DB] SQLALCHEMY_DATABASE_URI = {app.config['SQLALCHEMY_DATABASE_URI']}")

    # --- مقداردهی اکستنشن‌ها (فقط همین یک‌بار) ---
    init_extensions(app)

    # --- CORS برای auth API ---
    CORS(
            app,
            resources={r"/*": {"origins": "http://localhost:3000"}},
            supports_credentials=True,
            allow_headers=["Content-Type", "Authorization"],
            methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        )

    # --- user loader برای Flask-Login ---
    from .models.user import User
    # @app.route("/uploads/<path:filename>")
    # def uploaded_file(filename):
    #     upload_root = os.path.join(current_app.root_path, "..", "uploads")
    #     return send_from_directory(upload_root, filename)
    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return User.query.get(int(user_id))
        except Exception:
            return None

    # --- ثبت بلوپرینت‌ها ---
    app.register_blueprint(auth_bp)  # /auth و /auth/api/login

    from .blueprints.api import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    try:
        from .blueprints.api_auth import api_auth_bp
        app.register_blueprint(api_auth_bp, url_prefix="/api/auth")
    except Exception:
        pass

    # --- هندلرهای JWT ---
    @jwt.invalid_token_loader
    def invalid_token(reason):
        return {"message": "Invalid token", "reason": reason}, 401

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return {"message": "Token has expired"}, 401

    @jwt.unauthorized_loader
    def missing_token(reason):
        return {"message": "Missing or invalid Authorization header"}, 401

    # --- CLI: ساخت یوزر جدید ---
    @app.cli.command("create-user")
    def create_user():
        """Create a local user (dev)"""
        import click
        import getpass
        from .models.user import User
        from .extensions import db

        username = click.prompt("username").strip()
        email = click.prompt("email", default="", show_default=False).strip()
        phone = click.prompt("phone_number", default="", show_default=False).strip()
        password = getpass.getpass("password: ")

        if not username or not password:
            click.echo("username & password required")
            return

        # اینجا در app context هستیم، User.query امنه
        if User.query.filter_by(username=username).first():
            click.echo("User exists")
            return

        u = User(username=username)

        if email and hasattr(User, "email"):
            u.email = email
        if phone and hasattr(User, "phone_number"):
            u.phone_number = phone

        if hasattr(u, "set_password"):
            u.set_password(password)
        else:
            u.password_hash = password  # فقط اگر متد نداشتی (ولی تو داری)

        if hasattr(User, "is_active") and getattr(u, "is_active", None) is None:
            u.is_active = True

        db.session.add(u)
        db.session.commit()
        click.echo(f"User {username} created.")

    # --- CLI: ریست پسورد (برای Invalid salt / هش‌های قدیمی) ---
    @app.cli.command("set-password")
    def set_password():
        """Reset password for an existing user (re-hash with bcrypt)"""
        import click
        import getpass
        from .models.user import User
        username = click.prompt("username to reset").strip()
        u = User.query.filter_by(username=username).first()
        if not u:
            click.echo("User not found")
            return

        pwd1 = getpass.getpass("new password: ")
        pwd2 = getpass.getpass("repeat new password: ")
        if not pwd1 or pwd1 != pwd2:
            click.echo("Passwords do not match")
            return

        if hasattr(u, "set_password"):
            u.set_password(pwd1)
        else:
            u.password_hash = pwd1

        db.session.commit()
        click.echo(f"Password updated for {username}")

    return app
