from datetime import datetime
from app.extensions import db

class Payment(db.Model):
    __tablename__ = "payments"
    id         = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id", ondelete="CASCADE"), nullable=False, index=True)
    # 'IN' = دریافت از دانشجو (مثلاً شهریه) | 'OUT' = پرداخت به دانشجو/منتور/هزینه
    type       = db.Column(db.String(8), nullable=False, index=True)   # IN | OUT
    amount     = db.Column(db.Integer, nullable=False)                 # مبلغ به ریال/تومان (بر اساس سیاست شما)
    title      = db.Column(db.String(200), nullable=False)             # شرح تراکنش
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def signed_amount(self) -> int:
        return self.amount if (self.type or "IN").upper() == "IN" else -self.amount
