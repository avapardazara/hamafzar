# app/models/asset.py
from app.extensions import db
from datetime import date

class Asset(db.Model):
    __tablename__ = "assets"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=True)
    purchase_date = db.Column(db.Date, default=date.today)
    cost = db.Column(db.Float, nullable=False, default=0)
    depreciation_rate = db.Column(db.Float, nullable=True, default=0)  # درصد سالانه
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE / SOLD / DISPOSED
    note = db.Column(db.Text, nullable=True)

    def current_value(self):
        """محاسبه استهلاک خط مستقیم (برای نمایش در داشبورد)"""
        if not self.depreciation_rate or not self.purchase_date:
            return self.cost
        years = max((date.today() - self.purchase_date).days / 365, 0)
        depreciated = self.cost * (self.depreciation_rate / 100) * years
        return max(self.cost - depreciated, 0)
