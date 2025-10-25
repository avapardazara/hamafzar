# app/models/mentor_payment.py
from app.extensions import db
from datetime import datetime

class MentorPayment(db.Model):
    __tablename__ = "mentor_payments"

    id         = db.Column(db.Integer, primary_key=True)
    mentor_id  = db.Column(db.Integer, db.ForeignKey("mentors.id"), nullable=False, index=True)
    amount     = db.Column(db.Integer, nullable=False)            # مبلغ (تومان)
    kind       = db.Column(db.String(12), nullable=False)         # 'INCOME' (وصول/بستانکاری)، 'EXPENSE' (پرداخت به منتور)
    title      = db.Column(db.String(255), nullable=True)
    note       = db.Column(db.Text, nullable=True)
    paid_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    mentor = db.relationship("Mentor", backref=db.backref("payments", lazy="dynamic"))
