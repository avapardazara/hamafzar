from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user, login_required

def role_required(*roles):
    """
    استفاده:
      @role_required("admin")
      @role_required("ADMIN")
      @role_required("admin", "MENTOR")
      @role_required(["admin", "MENTOR"])
    همه چیز case-insensitive چک می‌شود.
    """

    # اگر یه لیست/تاپل تکی پاس داده شده بود:
    if len(roles) == 1 and isinstance(roles[0], (list, tuple, set)):
        roles = roles[0]

    allowed = {str(r).lower() for r in roles}

    def decorator(func):
        @wraps(func)
        @login_required
        def wrapper(*args, **kwargs):
            user_role = (getattr(current_user, "role", "") or "").lower()
            if user_role not in allowed:
                flash("دسترسی مجاز نیست.", "error")
                return redirect(url_for("dashboard.index"))
            return func(*args, **kwargs)
        return wrapper

    return decorator
