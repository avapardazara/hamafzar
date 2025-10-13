# app/models/payment.py
from datetime import datetime
from app.extensions import db

class Payment(db.Model):
    __tablename__ = "payments"

    id         = db.Column(db.Integer, primary_key=True)

    # برای دانشجو قبلاً بوده:
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="SET NULL", name="fk_payments_student_id"), nullable=True, index=True)

    # اضافه برای منتور:
    mentor_id  = db.Column(db.Integer, db.ForeignKey("mentors.id", ondelete="SET NULL", name="fk_payments_mentor_id"), nullable=True, index=True)

    # موجود در پروژه:
    type       = db.Column(db.String(8), nullable=False, default="IN", index=True)  # IN | OUT
    amount     = db.Column(db.Integer, nullable=False, default=0)
    title      = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # اضافه برای گزارش‌دهی/فیلتر بهتر در مالی منتورها:
    kind       = db.Column(db.String(10), nullable=False, default="INCOME", index=True)  # INCOME | EXPENSE
    status     = db.Column(db.String(20), nullable=True)  # PAID | DUE
    paid_at    = db.Column(db.DateTime, nullable=True)
    note       = db.Column(db.String(255), nullable=True)

    # روابط (اختیاری)
    mentor = db.relationship("Mentor", backref=db.backref("payments", cascade="all, delete-orphan"))
