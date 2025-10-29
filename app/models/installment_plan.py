from __future__ import annotations
from datetime import date
from sqlalchemy import Column, Integer, Float, String, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.extensions import db

class InstallmentPlan(db.Model):
    __tablename__ = "installment_plans"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"))
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"))
    enrollment_id = db.Column(db.Integer, db.ForeignKey("enrollments.id"))

    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    installments_count = db.Column(db.Integer, nullable=False, default=1)

    use_cheques = db.Column(db.Boolean, nullable=False, default=False)
    cheque_fee_percent = db.Column(db.Float, nullable=False, default=0.0)
    cheque_fee_total = db.Column(db.Float, nullable=False, default=0.0)
    note = Column(Text, nullable=True)

    first_due_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default="OPEN")  # OPEN/CLOSED

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    installments = db.relationship(
        "Installment",
        backref="plan",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )




