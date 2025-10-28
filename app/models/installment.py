from __future__ import annotations
from datetime import date
from sqlalchemy import Column, Integer, Float, String, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.extensions import db

class Installment(db.Model):
    __tablename__ = "installments"

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("installment_plans.id", ondelete="CASCADE"), index=True)

    # شماره قسط در برنامه
    seq = Column(Integer, nullable=False, default=1)

    # مبالغ
    amount_base = Column(Float, nullable=False, default=0.0)      # سهم از اصل مبلغ (total_amount / n)
    cheque_fee_amount = Column(Float, nullable=False, default=0.0) # سهم از کارمزد چک
    amount_total = Column(Float, nullable=False, default=0.0)      # amount_base + cheque_fee_amount

    # تاریخ‌ها
    due_date = Column(Date, nullable=True)

    # وضعیت
    status = Column(String(20), nullable=False, default="PENDING")   # PENDING/PAID/CANCELLED
    paid_at = Column(DateTime, nullable=True)

    # ارتباط اختیاری به Payment وقتی تسویه شد
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True, index=True)

    # اطلاعات چک (اختیاری، اگر use_cheques=True)
    cheque_number = Column(String(120), nullable=True)
    cheque_bank = Column(String(120), nullable=True)
    cheque_issuer = Column(String(120), nullable=True)
    cheque_issue_date = Column(Date, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # روابط
    plan = relationship("InstallmentPlan", back_populates="installments")
