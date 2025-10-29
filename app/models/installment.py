# app/models/installment.py
from __future__ import annotations
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.extensions import db


class InstallmentPlan(db.Model):
    __tablename__ = "installment_plans"

    id = Column(Integer, primary_key=True)

    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    total_amount = Column(Float, nullable=False, default=0.0)
    surcharge_percent = Column(Float, nullable=False, default=0.0)
    surcharge_amount = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    installments = relationship(
        "Installment",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class Installment(db.Model):
    __tablename__ = "installments"

    id = Column(Integer, primary_key=True)

    # FK ضروری که قبلاً خطا به‌خاطر نبودنش بود
    plan_id = Column(Integer, ForeignKey("installment_plans.id", ondelete="CASCADE"), nullable=False)

    number = Column(Integer, nullable=False, default=1)
    due_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False, default=0.0)
    surcharge_amount = Column(Float, nullable=False, default=0.0)

    status = Column(String(20), nullable=False, default="PENDING")  # PENDING/PAID/CANCELLED/BOUNCED
    paid_at = Column(DateTime, nullable=True)

    cheque_number = Column(String(64), nullable=True)
    bank_name = Column(String(120), nullable=True)
    issuer_name = Column(String(120), nullable=True)
    issue_date = Column(Date, nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    plan = relationship("InstallmentPlan", back_populates="installments")
