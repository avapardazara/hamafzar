from __future__ import annotations
from datetime import datetime, date
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Index,
    ForeignKey,
    func,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.extensions import db

class Payment(db.Model):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # نوع تراکنش
    kind: Mapped[str] = mapped_column(db.String(20), nullable=False, default="tuition")
    # وضعیت پرداخت
    status: Mapped[str] = mapped_column(db.String(20), nullable=False, default="pending")

    # اطلاعات مالی
    amount: Mapped[int] = mapped_column(db.Integer, nullable=False, default=0)
    title: Mapped[Optional[str]] = mapped_column(db.String(255), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)

    # ارتباط‌ها
    course_id: Mapped[Optional[int]] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    student_id: Mapped[Optional[int]] = mapped_column(ForeignKey("students.id"), nullable=True, index=True)
    mentor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("mentors.id"), nullable=True, index=True)

    # تاریخ‌ها
    paid_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(db.Date, nullable=True, index=True)

    # زمان ایجاد رکورد (برای sort در لیست‌ها)
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime, nullable=False, server_default=func.current_timestamp(), index=True
    )

    # روابط ORM
    course = relationship("Course", backref=db.backref("payments", lazy="dynamic"))
    student = relationship("Student", backref=db.backref("payments", lazy="dynamic"))
    mentor = relationship("Mentor", backref=db.backref("payments", lazy="dynamic"))

    __table_args__ = (
        CheckConstraint("kind in ('tuition','mentor_share')", name="ck_payments_kind"),
        CheckConstraint("status in ('paid','pending','unpaid')", name="ck_payments_status"),
        Index("ix_payments_kind_status_course", "kind", "status", "course_id"),
    )

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"

    @property
    def is_overdue(self) -> bool:
        return (self.status != "paid") and (self.due_date is not None) and (self.due_date < date.today())

    @property
    def status_color(self) -> str:
        return "#02AD82" if self.is_paid else "red"

    @classmethod
    def total_amount(cls, *filters):
        q = db.session.query(func.coalesce(func.sum(cls.amount), 0))
        for f in filters:
            q = q.filter(f)
        return int(q.scalar() or 0)

    @classmethod
    def count_overdue(cls, *filters):
        q = db.session.query(func.count(cls.id)).filter(
            cls.status != "paid",
            cls.due_date.isnot(None),
            cls.due_date < func.current_date()
        )
        for f in filters:
            q = q.filter(f)
        return int(q.scalar() or 0)
