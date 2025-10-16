from datetime import datetime
from app.extensions import db

class Course(db.Model):
    __tablename__ = "courses"
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(200), nullable=False, index=True)
    mentor_name = db.Column(db.String(120))         
    status      = db.Column(db.String(20), default="ACTIVE")  
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey("mentors.id"), nullable=True)
    mentor = db.relationship("Mentor", backref="courses", lazy=True)
    description = db.Column(db.Text)
    start_date  = db.Column(db.Date)               
    end_date    = db.Column(db.Date)               
    cover_path  = db.Column(db.String(255))        
# زمان‌بندی جلسات
    # DATES | WEEKLY | ODD | EVEN
    schedule_type    = db.Column(db.String(16))
    # برای WEEKLY: مثلا "SAT,MON"  (شنبه، دوشنبه)
    schedule_days    = db.Column(db.String(32))
    # اگر الگوی دیگری خواستی (مثلا ساعات/شیفت یا ODD/EVEN)، اینجا ذخیره می‌شود
    schedule_pattern = db.Column(db.String(32))

    # مالی
    tuition_per_student   = db.Column(db.Integer)   # شهریه هر دانشجو
    installment_enabled   = db.Column(db.Boolean)   # اقساطی هست؟
    installment_count     = db.Column(db.Integer)   # تعداد اقساط
    mentor_share_percent  = db.Column(db.Integer)   # درصد سهم منتور از درآمد کل

    created_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def fee_per_student(self):
        return self.tuition_per_student
    
    @fee_per_student.setter
    def fee_per_student(self, val):
        try:
            self.tuition_per_student = int(val) if val not in (None, "") else None
        except ValueError:
            self.tuition_per_student = None



    def __repr__(self):
        return f"<Course id={self.id} title={self.title!r}>"
    


