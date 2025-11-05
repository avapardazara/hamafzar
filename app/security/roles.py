# -*- coding: utf-8 -*-
# منبع واحد نقش‌ها و سیاست‌های سطح دسترسی (قابل گسترش)
ROLES = ["student", "mentor", "admin", "superadmin"]

# نمونه‌ی سیاست‌ها برای توسعه‌های بعدی (dashboard/data/ops)
POLICY = {
    # مثال‌ها – در مرحله‌ی بعد روی هر endpoint/منبع اعمال می‌کنیم
    "dashboard:student": {"roles": ["student"]},
    "dashboard:mentor": {"roles": ["mentor", "admin", "superadmin"]},
    "dashboard:admin": {"roles": ["admin", "superadmin"]},

    "installments:view": {"roles": ["student", "mentor", "admin", "superadmin"]},
    "installments:write": {"roles": ["admin", "superadmin"]},  # عملیات حساس مالی
    "courses:view": {"roles": ["student", "mentor", "admin", "superadmin"]},
    "mentors:view": {"roles": ["mentor", "admin", "superadmin"]},
    "students:view": {"roles": ["admin", "superadmin"]},
}

def allowed_roles(permission_key: str):
    cfg = POLICY.get(permission_key) or {}
    return cfg.get("roles", [])
