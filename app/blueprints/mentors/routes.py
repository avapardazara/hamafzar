# app/blueprints/mentors/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import func, literal
from ...extensions import db
from ...models.mentor import Mentor
from ...models.course import Course
from ...models.enrollment import Enrollment
from ...utils.files import save_student_avatar  # از همین util برای آپلود استفاده می‌کنیم
from sqlalchemy.orm.attributes import InstrumentedAttribute

bp = Blueprint("mentors", __name__, url_prefix="/mentors")


# -------------------------------
# Helpers
# -------------------------------
def _coalesce(val, default):
    return val if val is not None else default


def _mentor_finance_summary(mentor_id: int):
    """
    خروجی JSON مانند:
    {
      "items": [
        {
          "course_id": 1,
          "course_title": "...",
          "students": 5,
          "fee_per_student": 1000000,
          "share_percent": 20,
          "income_total": 5000000,
          "mentor_share": 1000000
        },
        ...
      ],
      "totals": {
         "share_total": ...,
         "paid_total": 0,     # فعلا پرداختیِ منتور نداریم
         "balance": ...
      }
    }
    """
    # تعداد دانشجوهای هر دوره‌ای که منتورش این mentor است
    rows = (
        db.session.query(
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            func.coalesce(Course.fee_per_student, 0).label("fee_per_student"),
            func.coalesce(Course.mentor_share_percent, 0).label("share_percent"),
            func.count(Enrollment.id).label("students_count"),
        )
        .select_from(Course)
        .outerjoin(Enrollment, Enrollment.course_id == Course.id)
        .filter(Course.mentor_id == mentor_id)
        .group_by(Course.id)
        .all()
    )

    items = []
    total_share = 0

    for r in rows:
        fee = int(_coalesce(r.fee_per_student, 0))
        share_pct = float(_coalesce(r.share_percent, 0.0))
        students = int(_coalesce(r.students_count, 0))
        income_total = fee * students
        mentor_share = int(round(income_total * (share_pct / 100.0)))
        total_share += mentor_share

        items.append({
            "course_id": r.course_id,
            "course_title": r.course_title,
            "students": students,
            "fee_per_student": fee,
            "share_percent": share_pct,
            "income_total": int(income_total),
            "mentor_share": int(mentor_share),
        })

    paid_total = 0  # در این نسخه مدل پرداخت منتور نداریم
    balance = int(total_share - paid_total)

    return {
        "items": items,
        "totals": {
            "share_total": int(total_share),
            "paid_total": int(paid_total),
            "balance": int(balance),
        },
    }


# -------------------------------
# List
# -------------------------------
@bp.get("/")
@login_required
def list():
    q = (request.args.get("q") or "").strip()
    query = Mentor.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            (Mentor.first_name.ilike(like)) |
            (Mentor.last_name.ilike(like)) |
            (Mentor.email.ilike(like)) |
            (Mentor.phone.ilike(like))
        )

    mentors = query.order_by(Mentor.created_at.desc()).all()
    # قالب index.html دقیقا این متغیرها را می‌خواهد:
    return render_template("mentors/index.html", mentors=mentors, q=q)


# -------------------------------
# Create (GET form.html) + POST
# قالب form.html بدون action ارسال می‌کند -> همان URL باید POST را هم بپذیرد
# -------------------------------
@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_form():
    if request.method == "POST":
        f = request.form
        first = (f.get("first_name") or "").strip()
        last = (f.get("last_name") or "").strip()
        email = (f.get("email") or "").strip() or None
        phone = (f.get("phone") or "").strip() or None

        if not first or not last:
            flash("نام و نام خانوادگی الزامی است.", "error")
            return redirect(url_for("mentors.create_form"))

        m = Mentor(first_name=first, last_name=last, email=email, phone=phone)
        db.session.add(m)
        db.session.commit()

        # آپلود آواتار (اختیاری)
        file = request.files.get("avatar")
        if file and file.filename:
            # از util موجود استفاده می‌کنیم و همان مسیر students را برای ذخیره بکار می‌بریم
            rel = save_student_avatar(file, m.id)
            if rel:
                # در مدل Mentor در پروژه شما فیلد آواتار معمولا m.avatar یا m.avatar_path است؛
                # طبق قالب‌ها m.avatar استفاده می‌شود:
                m.avatar = rel
                db.session.commit()

        flash("منتور با موفقیت ایجاد شد.", "success")
        return redirect(url_for("mentors.edit_form", mentor_id=m.id))

    # GET
    return render_template("mentors/form.html", m=None)


# -------------------------------
# Edit (profile) – edit.html
# -------------------------------
@bp.get("/<int:mentor_id>/edit")
@login_required
def edit_form(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)

    taught = Course.query.filter(Course.mentor_id == m.id).order_by(Course.created_at.desc()).all()
    all_courses = Course.query.order_by(Course.created_at.desc()).all()

    # اگر شمارش مهارت برای منتورها ندارید، صفر پاس می‌دهیم
    skills_count = 0

    # خلاصه مالی برای نمایش عدد تراز در هدر
    summary = _mentor_finance_summary(m.id)
    totals = summary["totals"]

    # back url
    back_url = request.referrer or url_for("mentors.list")

    return render_template(
        "mentors/edit.html",
        m=m,
        taught=taught,
        all_courses=all_courses,
        skills_count=skills_count,
        totals=totals,
        back_url=back_url
    )


# -------------------------------
# Update basic fields (from tab-basic form)
# -------------------------------
@bp.post("/<int:mentor_id>/basic")
@login_required
def update_basic(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    f = request.form
    m.first_name = (f.get("first_name") or "").strip()
    m.last_name  = (f.get("last_name") or "").strip()
    m.phone      = (f.get("phone") or "").strip() or None
    m.email      = (f.get("email") or "").strip() or None

    db.session.commit()
    flash("اطلاعات ذخیره شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))


# -------------------------------
# Upload avatar (from edit header button)
# -------------------------------
@bp.post("/<int:mentor_id>/upload-avatar")
@login_required
def upload_avatar(mentor_id):
    m = Mentor.query.get_or_404(mentor_id)
    file = request.files.get("avatar")
    if file and file.filename:
        rel = save_student_avatar(file, m.id)
        if rel:
            m.avatar = rel
            db.session.commit()
            flash("تصویر پروفایل به‌روزرسانی شد.", "success")
        else:
            flash("آپلود تصویر ناموفق بود.", "error")
    else:
        flash("فایلی انتخاب نشد.", "error")
    return redirect(url_for("mentors.edit_form", mentor_id=m.id))


# -------------------------------
# Assign / remove course for mentor (tab-courses)
# -------------------------------
@bp.post("/<int:mentor_id>/courses/add")
@login_required
def add_course(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    cid = request.form.get("course_id")
    if not cid:
        flash("شناسه دوره نامعتبر است.", "error")
        return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))

    c = Course.query.get_or_404(int(cid))
    c.mentor_id = mentor_id
    db.session.commit()
    flash("دوره به منتور نسبت داده شد.", "success")
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))


@bp.post("/<int:mentor_id>/courses/<int:course_id>/remove")
@login_required
def remove_course(mentor_id, course_id):
    Mentor.query.get_or_404(mentor_id)
    c = Course.query.get_or_404(course_id)
    if c.mentor_id == mentor_id:
        c.mentor_id = None
        db.session.commit()
        flash("ارتباط منتور و دوره حذف شد.", "info")
    return redirect(url_for("mentors.edit_form", mentor_id=mentor_id))


# -------------------------------
# Finance summary (used by edit.html JS -> /mentors/<id>/finance/summary)
# -------------------------------
@bp.get("/<int:mentor_id>/finance/summary")
@login_required
def finance_summary(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    return jsonify(_mentor_finance_summary(mentor_id))


# -------------------------------
# Payments endpoints used by JS در تب مالی
# فعلا چون مدل پرداخت منتور نداریم، خالی برمی‌گردانیم
# تا UI بدون خطا کار کند و اعداد کارت بالا از summary پر شود.
# -------------------------------
@bp.get("/<int:mentor_id>/payments")
@login_required
def payments_list(mentor_id):
    Mentor.query.get_or_404(mentor_id)
    totals = _mentor_finance_summary(mentor_id)["totals"]
    return jsonify(ok=True, items=[], totals=totals)


@bp.post("/<int:mentor_id>/payments")
@login_required
def payments_add(mentor_id):
    # در آینده: اینجا ذخیره پرداخت به منتور را اضافه کنید.
    return jsonify(ok=True)


@bp.delete("/<int:mentor_id>/payments/<int:pay_id>")
@login_required
def payments_delete(mentor_id, pay_id):
    # در آینده: حذف پرداخت منتور
    return jsonify(ok=True)

# --- کمکی: اگر ستون واقعی نبود، literal(default) برگردان ---
def _sa_col_or_literal(model, attr_name: str, default_value=0):
    """اگر attr ستونی از نوع SQLAlchemy نبود، literal(default) بده."""
    attr = getattr(model, attr_name, None)
    if isinstance(attr, InstrumentedAttribute):
        return attr
    return literal(default_value)


# --- این تابع را کامل جایگزین نسخه فعلی‌اش کن ---
def _mentor_finance_summary(mentor_id: int):
    """
    خروجی:
    {
      "items": [
        {"course_id":.., "course_title":.., "students":.., "fee_per_student":..,
         "share_percent":.., "income_total":.., "mentor_share":..}
      ],
      "totals": {"income_total":.., "share_total":.., "paid_total": 0, "balance": ..}
    }
    """
    # ستون‌های «ایمن» (اگر ستون واقعی نبود 0 می‌گذاریم)
    fee_col   = _sa_col_or_literal(Course, "fee_per_student", 0)
    share_col = _sa_col_or_literal(Course, "mentor_share_percent", 0)

    rows = (
        db.session.query(
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            func.coalesce(fee_col, 0).label("fee_per_student"),
            func.coalesce(share_col, 0).label("share_percent"),
            func.count(Enrollment.id).label("students_count"),
        )
        .outerjoin(Enrollment, Enrollment.course_id == Course.id)
        .filter(Course.mentor_id == mentor_id)
        .group_by(Course.id)
        .all()
    )

    items = []
    income_total = 0
    share_total  = 0

    for r in rows:
        students = int(r.students_count or 0)
        fee      = int(r.fee_per_student or 0)
        share_pr = float(r.share_percent or 0)

        income = students * fee  # درآمد کل دوره
        share  = int(round(income * (share_pr / 100.0)))  # سهم منتور

        items.append({
            "course_id": r.course_id,
            "course_title": r.course_title,
            "students": students,
            "fee_per_student": fee,
            "share_percent": share_pr,
            "income_total": income,
            "mentor_share": share,
        })

        income_total += income
        share_total  += share

    # اگر پرداخت‌های منتور هم پیاده‌سازی شده، اینجا جمع پرداخت‌ها را جای آن بگذار
    paid_total = 0
    balance    = share_total - paid_total

    return {
        "items": items,
        "totals": {
            "income_total": int(income_total),
            "share_total":  int(share_total),
            "paid_total":   int(paid_total),
            "balance":      int(balance),
        },
    }