from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
bcrypt = Bcrypt()
cors = CORS()
login_manager = LoginManager()

def init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    # CORS فقط برای API
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=False)

    # حفظ سازگاری با کدهای قدیمی (در صورت وجود)
    login_manager.init_app(app)
    login_manager.login_view = None  # گارد سمت فرانت می‌گیریم

# اگر جایی از قبل init_app ایمپورت می‌شد:
def init_app(app):
    return init_extensions(app)
