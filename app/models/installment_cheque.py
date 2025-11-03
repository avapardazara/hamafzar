from app.extensions import db

class InstallmentCheque(db.Model):
    __tablename__ = "installment_cheques"

    id = db.Column(db.Integer, primary_key=True)
    installment_id = db.Column(
        db.Integer,
        db.ForeignKey("installments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    cheque_number = db.Column(db.String(64), nullable=False)
    bank_name     = db.Column(db.String(120))
    amount        = db.Column(db.Numeric(18, 2))   # مبلغ روی چک (اختیاری)
    issue_date    = db.Column(db.Date)
    due_date      = db.Column(db.Date)
    status        = db.Column(db.String(32))       # ISSUED/CLEARED/RETURNED/...
    note          = db.Column(db.Text)

    created_at    = db.Column(db.DateTime, server_default=db.func.now())
    updated_at    = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f"<InstallmentCheque #{self.id} {self.cheque_number}>"
