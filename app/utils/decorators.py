from functools import wraps
from flask import redirect, url_for, flash
from flask_login import current_user

def role_required(roles):
    """ Decorator to check if user has the required role(s). """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # بررسی که role کاربر در لیست roles قرار داره یا نه
            if current_user.role not in roles:
                flash("دسترسی مجاز نیست.", "error")
                return redirect(url_for("dashboard.index"))  # یا هر صفحه دیگه‌ای که مناسب باشه
            return func(*args, **kwargs)
        return wrapper
    return decorator
