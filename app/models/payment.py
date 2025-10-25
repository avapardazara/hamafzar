# app/models/payment.py
from __future__ import annotations
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, ForeignKey, Text
from sqlalchemy.sql import func
from app.extensions import db

class Payment(db.Model):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    # kind: نوع پرداخت / دریافتی، مثلا 'tuition' یا 'mentor_share' یا 'adjustment'
    kind = Column(String(50), nullable=False, default='tuition')
    # وضعیت: 'paid' / 'pending' / 'cancelled' ...
    status = Column(String(30), nullable=False, default='paid')
    amount = Column(Float, nullable=False, default=0.0)
    title = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)

    # ارتباط‌ها (قابل نال برای ردیف‌های عمومی)
    course_id = Column(Integer, ForeignKey('courses.id'), nullable=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=True)
    mentor_id = Column(Integer, ForeignKey('mentors.id'), nullable=True)

    paid_at = Column(DateTime, nullable=True)     # زمان پرداخت (نقدی)
    due_date = Column(Date, nullable=True)        # تاریخ سررسید (برای اقساط و فیش‌ها)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Payment id={self.id} kind={self.kind} amount={self.amount}>"
