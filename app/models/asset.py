from app.extensions import db
class Asset(db.Model):
    __tablename__ = 'assets'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(120))
    code = db.Column(db.String(120), unique=True)
    quantity = db.Column(db.Integer, default=1)
    unit = db.Column(db.String(32))
    location = db.Column(db.String(200))
    status = db.Column(db.String(32))
    purchase_date = db.Column(db.Date)
    purchase_price = db.Column(db.Numeric(18, 2))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f"<Asset {self.name}>"
