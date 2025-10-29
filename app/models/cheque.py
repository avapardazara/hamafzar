from datetime import datetime
from app.extensions import db

class Cheque(db.Model):
    __tablename__ = "cheques"

    id = db.Column(db.Integer, primary_key=True)
    installment_id = db.Column(db.Integer, db.ForeignKey("installments.id"), nullable=False, index=True)
    installment = db.relationship("Installment", backref=db.backref("cheques", lazy=True, cascade="all, delete-orphan"))

    cheque_number = db.Column(db.String(100))
    bank_name     = db.Column(db.String(100))
    issuer_name   = db.Column(db.String(100))

    issue_date = db.Column(db.Date)
    due_date   = db.Column(db.Date)
    amount     = db.Column(db.Float)

    status = db.Column(db.String(20), nullable=False, default="PENDING")  # PENDING/CLEARED/BOUNCED
    note   = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<Cheque id={self.id} no={self.cheque_number}>"
