# app/models/__init__.py

# هسته‌ای
from .user import User  # اگر داری

# موجودیت‌های اصلی
try:
    from .core import Student
except Exception:
    Student = None

try:
    from .mentor import Mentor
except Exception:
    Mentor = None

try:
    from .skill import Skill, StudentSkill
except Exception:
    Skill = StudentSkill = None

# دوره و وابسته‌ها
try:
    from .course import Course  # مدل Course
except Exception:
    Course = None

# جلسات و حضور
try:
    from .course_session import CourseSession, Attendance
except Exception:
    CourseSession = Attendance = None

# پرداخت‌ها (اگر داری)
try:
    from .payment import Payment
except Exception:
    Payment = None

# هر مدل دیگری که در پروژه‌ات هست را به همین الگو اضافه کن.
try:
    from .enrollment import Enrollment
except Exception:
    Enrollment = None

try:
    from .asset import Asset
except Exception:
    Asset = None
try:
    from .mentor_payment import MentorPayment
except Exception:
    MentorPayment = None
try:
    from .expense import Expense
except Exception:
    Expense = None
try:
    from .installment import Installment
except Exception:
    Installment = None
try:
    from .installment_plan import InstallmentPlan
except Exception:
    InstallmentPlan = None
try:
    from .installment_cheque import InstallmentCheque
except Exception:
    InstallmentCheque = None