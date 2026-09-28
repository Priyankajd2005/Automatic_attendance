"""
app/routes/admin.py
--------------------
Admin panel: Google Sheets sync, manage subjects, manage teachers,
create demo data.
"""

import os
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, current_app, jsonify
)
from flask_login import login_required, current_user

from app import db
from app.models import Student, Subject, Teacher, AttendanceSession, AttendanceRecord
from app.services import face_service
from app.services import google_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------------------------------------------------------------------
# Admin index
# ---------------------------------------------------------------------------

@admin_bp.route("/")
@login_required
def index():
    stats = {
        "students":  Student.query.filter_by(is_active=True).count(),
        "subjects":  Subject.query.count(),
        "teachers":  Teacher.query.count(),
        "sessions":  AttendanceSession.query.count(),
        "records":   AttendanceRecord.query.count(),
        "encodings": _count_encodings(),
    }
    return render_template("admin/index.html", stats=stats)


def _count_encodings() -> int:
    folder = current_app.config.get("FACE_DATA_FOLDER", "face_data")
    if not os.path.exists(folder):
        return 0
    return len([f for f in os.listdir(folder) if f.endswith(".npy")])


# ---------------------------------------------------------------------------
# Google Sheets sync
# ---------------------------------------------------------------------------

@admin_bp.route("/sync", methods=["GET", "POST"])
@login_required
def sync_google():
    """Sync students from a Google Sheet."""
    default_mapping = {
        "full_name":   "Full Name",
        "roll_number": "Roll Number",
        "college":     "College Name",
        "department":  "Department",
        "semester":    "Semester",
        "student_id":  "Student ID",
        "email":       "Email Address",
        "phone":       "Phone Number",
        "photo1":      "Front Photo",
        "photo2":      "Left Photo",
        "photo3":      "Right Photo",
    }

    if request.method == "POST":
        spreadsheet_id = request.form.get("spreadsheet_id", "").strip()
        sheet_name     = request.form.get("sheet_name", "Form Responses 1").strip()
        creds_file     = current_app.config.get(
            "GOOGLE_CREDENTIALS_FILE", "google_credentials.json"
        )

        # Build column mapping from form
        column_mapping = {}
        for field in default_mapping:
            val = request.form.get(f"col_{field}", default_mapping[field]).strip()
            if val:
                column_mapping[field] = val

        if not spreadsheet_id:
            flash("Please enter a Google Spreadsheet ID.", "danger")
            return render_template("admin/sync.html", default_mapping=default_mapping)

        photo_save_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "photos")

        result = google_service.sync_students_from_sheet(
            spreadsheet_id=spreadsheet_id,
            credentials_file=creds_file,
            column_mapping=column_mapping,
            photo_save_dir=photo_save_dir,
            sheet_name=sheet_name,
        )

        added = 0
        updated = 0
        skipped = 0

        for sdata in result["students"]:
            roll = sdata.get("roll_number", "").upper()
            if not roll:
                skipped += 1
                continue

            existing = Student.query.filter_by(roll_number=roll).first()
            if existing:
                # Update info
                existing.full_name  = sdata.get("full_name") or existing.full_name
                existing.college    = sdata.get("college")    or existing.college
                existing.department = sdata.get("department") or existing.department
                existing.semester   = sdata.get("semester")   or existing.semester
                existing.email      = sdata.get("email")      or existing.email
                existing.phone      = sdata.get("phone")      or existing.phone
                if sdata.get("photo1_path"):
                    existing.photo1_path = sdata["photo1_path"]
                if sdata.get("photo2_path"):
                    existing.photo2_path = sdata["photo2_path"]
                if sdata.get("photo3_path"):
                    existing.photo3_path = sdata["photo3_path"]
                db.session.flush()
                _encode_student(existing)
                updated += 1
            else:
                student = Student(
                    full_name=sdata.get("full_name", ""),
                    roll_number=roll,
                    college=sdata.get("college", ""),
                    department=sdata.get("department", ""),
                    semester=sdata.get("semester", ""),
                    student_id=sdata.get("student_id", ""),
                    email=sdata.get("email", ""),
                    phone=sdata.get("phone", ""),
                    photo1_path=sdata.get("photo1_path"),
                    photo2_path=sdata.get("photo2_path"),
                    photo3_path=sdata.get("photo3_path"),
                )
                db.session.add(student)
                db.session.flush()
                _encode_student(student)
                added += 1

        db.session.commit()

        flash(
            f"Sync complete: {added} added, {updated} updated, {skipped} skipped. "
            f"{len(result['errors'])} error(s).",
            "success" if not result["errors"] else "warning",
        )
        if result["errors"]:
            for err in result["errors"][:5]:
                flash(err, "warning")

        return redirect(url_for("admin.sync_google"))

    return render_template("admin/sync.html", default_mapping=default_mapping)


def _encode_student(student: Student):
    """Helper: encode a student's face photos and save the .npy file."""
    image_paths = [p for p in student.photo_paths if p and os.path.exists(p)]
    if not image_paths:
        return
    enc_path = face_service.save_student_encoding(
        student_id=student.id,
        roll_number=student.roll_number,
        image_paths=image_paths,
        face_data_folder=current_app.config["FACE_DATA_FOLDER"],
    )
    if enc_path:
        student.face_encoding_path = enc_path


# ---------------------------------------------------------------------------
# Subjects management
# ---------------------------------------------------------------------------

@admin_bp.route("/subjects")
@login_required
def subjects():
    all_subjects = Subject.query.order_by(Subject.department, Subject.name).all()
    return render_template("admin/subjects.html", subjects=all_subjects)


@admin_bp.route("/subjects/add", methods=["POST"])
@login_required
def add_subject():
    name       = request.form.get("name", "").strip()
    code       = request.form.get("code", "").strip()
    college    = request.form.get("college", "").strip()
    department = request.form.get("department", "").strip()
    semester   = request.form.get("semester", "").strip()

    if not name:
        flash("Subject name is required.", "danger")
        return redirect(url_for("admin.subjects"))

    subject = Subject(name=name, code=code, college=college, department=department, semester=semester)
    db.session.add(subject)
    db.session.commit()
    flash(f"Subject '{name}' added.", "success")
    return redirect(url_for("admin.subjects"))


@admin_bp.route("/subjects/<int:subject_id>/delete", methods=["POST"])
@login_required
def delete_subject(subject_id: int):
    subject = Subject.query.get_or_404(subject_id)
    db.session.delete(subject)
    db.session.commit()
    flash(f"Subject '{subject.name}' deleted.", "info")
    return redirect(url_for("admin.subjects"))


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------

@admin_bp.route("/teachers")
@login_required
def teachers():
    all_teachers = Teacher.query.order_by(Teacher.full_name).all()
    return render_template("admin/teachers.html", teachers=all_teachers)


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

@admin_bp.route("/demo", methods=["POST"])
@login_required
def create_demo_data():
    """Insert sample subjects and a demo teacher for testing."""
    demo_subjects = [
        ("Mathematics", "MATH101", "Engineering", "1"),
        ("Physics", "PHY101", "Engineering", "1"),
        ("Chemistry", "CHEM101", "Engineering", "1"),
        ("Programming in C", "CS101", "Computer Science", "1"),
        ("Data Structures", "CS201", "Computer Science", "3"),
        ("Database Management", "CS301", "Computer Science", "5"),
        ("Machine Learning", "CS401", "Computer Science", "7"),
        ("English Communication", "ENG101", "All", "1"),
    ]

    added = 0
    for name, code, dept, sem in demo_subjects:
        if not Subject.query.filter_by(code=code).first():
            db.session.add(Subject(name=name, code=code, department=dept, semester=sem))
            added += 1

    db.session.commit()
    flash(f"Demo data created: {added} subjects added.", "success")
    return redirect(url_for("admin.index"))
