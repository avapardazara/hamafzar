from __future__ import annotations
from datetime import date
from sqlalchemy import Column, Integer, Float, String, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.extensions import db

class InstallmentPlan(db.Model):
    __tablename__ = "installment_plans"

    id = Column(Integer, primary_key=True)

    # ارتباط‌ها
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("enrollments.id"), nullable=True, index=True)

    # پیکربندی کلی
    total_amount = Column(Float, nullable=False, default=0.0)     # مبلغ پایه (شهریه/قابل قسط‌بندی) قبل از کارمزد چک
    installments_count = Column(Integer, nullable=False, default=1)
    use_cheques = Column(Boolean, nullable=False, default=False)
    cheque_fee_percent = Column(Float, nullable=False, default=0.0)   # درصد کارمزد بابت چک روی کل مبلغ پایه
    cheque_fee_total = Column(Float, nullable=False, default=0.0)     # کارمزد محاسبه‌شده (total_amount * pct)

    # تاریخ شروع/سررسید اول
    first_due_date = Column(Date, nullable=True)

    # توضیحات
    title = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)

    # وضعیت کلی
    status = Column(String(20), nullable=False, default="OPEN")   # OPEN/CLOSED/CANCELLED

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # روابط
    installments = relationship("Installment", back_populates="plan", cascade="all, delete-orphan")
