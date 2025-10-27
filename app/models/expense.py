# app/models/expense.py
from app.extensions import db
from datetime import date

class Expense(db.Model):
    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    paid_at = db.Column(db.Date, default=date.today)
    related_course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    description = db.Column(db.Text, nullable=True)

    course = db.relationship("Course", backref="expenses", lazy="select")
