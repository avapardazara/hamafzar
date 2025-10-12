from flask import Blueprint

bp = Blueprint("finance", __name__, url_prefix="/finance")

@bp.get("/")
def index():
    return "💳 صفحه‌ی مالی (در حال ساخت)"
