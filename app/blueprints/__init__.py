from .auth.routes import bp as auth_bp
from .dashboard.routes import bp as dashboard_bp
from .courses.routes import bp as courses_bp
from .students.routes import bp as students_bp
from .mentors.routes import bp as mentors_bp
from .finance.routes import bp as finance_bp
from .admin.routes import bp as admin_bp  
from app.blueprints.attendance import bp as attendance_bp

blueprints = [auth_bp, dashboard_bp, courses_bp, students_bp, mentors_bp, finance_bp, admin_bp, attendance_bp]
