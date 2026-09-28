"""
app/routes/student.py
---------------------
Student management: list, register (manual), view, edit, delete.
"""

import os
import uuid
from pathlib import Path
from typing import Optional

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
    jsonify,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from app.models import Student
from app.services import face_service


student_bp = Blueprint("student", __name__, url_prefix="/students")

ALLOWED = {"png", "jpg", "jpeg", "webp"}


def _allowed(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED
    )


def _save_photo(
    file_obj,
    roll_number: str,
    suffix: str
) -> Optional[str]:
    """Save an uploaded photo and return its path."""

    if not file_obj or file_obj.filename == "":
        return None

    if not _allowed(file_obj.filename):
        return None

    ext = file_obj.filename.rsplit(".", 1)[1].lower()

    filename = secure_filename(
        f"{roll_number}_{suffix}_{uuid.uuid4().hex[:6]}.{ext}"
    )

    folder = os.path.join(
        current_app.config["UPLOAD_FOLDER"],
        "photos"
    )

    os.makedirs(folder, exist_ok=True)

    path = os.path.join(folder, filename)

    file_obj.save(path)

    return path


# ---------------------------------------------------------------------------
# List students
# ---------------------------------------------------------------------------

@student_bp.route("/")
@login_required
def list_students():

    dept = request.args.get("department", "")
    semester = request.args.get("semester", "")
    search = request.args.get("q", "").strip()

    query = Student.query.filter_by(is_active=True)

    if dept:
        query = query.filter(
            Student.department.ilike(f"%{dept}%")
        )

    if semester:
        query = query.filter_by(
            semester=semester
        )

    if search:
        query = query.filter(
            db.or_(
                Student.full_name.ilike(f"%{search}%"),
                Student.roll_number.ilike(f"%{search}%"),
            )
        )

    students = (
        query
        .order_by(Student.registered_at.desc())
        .all()
    )

    departments = [
        r[0]
        for r in db.session.query(
            Student.department
        ).distinct().all()
        if r[0]
    ]

    semesters = [
        r[0]
        for r in db.session.query(
            Student.semester
        ).distinct().all()
        if r[0]
    ]

    return render_template(
        "student/list.html",
        students=students,
        departments=departments,
        semesters=semesters,
        current_dept=dept,
        current_sem=semester,
        search=search,
    )


# ---------------------------------------------------------------------------
# Register new student
# ---------------------------------------------------------------------------

@student_bp.route("/register", methods=["GET", "POST"])
@login_required
def register():

    if request.method == "POST":

        roll_number = (
            request.form.get("roll_number", "")
            .strip()
            .upper()
        )

        full_name = (
            request.form.get("full_name", "")
            .strip()
        )

        college = (
            request.form.get("college", "")
            .strip()
        )

        department = (
            request.form.get("department", "")
            .strip()
        )

        semester = (
            request.form.get("semester", "")
            .strip()
        )

        student_id = (
            request.form.get("student_id", "")
            .strip()
        )

        email = (
            request.form.get("email", "")
            .strip()
        )

        phone = (
            request.form.get("phone", "")
            .strip()
        )

        if not roll_number or not full_name:

            flash(
                "Full Name and Roll Number are required.",
                "danger"
            )

            return render_template(
                "student/register.html"
            )

        if Student.query.filter_by(
            roll_number=roll_number
        ).first():

            flash(
                f"A student with Roll Number "
                f"'{roll_number}' already exists.",
                "warning"
            )

            return render_template(
                "student/register.html"
            )

        # Save uploaded photos
        photo1_path = _save_photo(
            request.files.get("photo1"),
            roll_number,
            "front"
        )

        photo2_path = _save_photo(
            request.files.get("photo2"),
            roll_number,
            "left"
        )

        photo3_path = _save_photo(
            request.files.get("photo3"),
            roll_number,
            "right"
        )

        if not photo1_path:

            flash(
                "At least one face photo (front) is required.",
                "danger"
            )

            return render_template(
                "student/register.html"
            )

        # Create student record
        student = Student(
            full_name=full_name,
            roll_number=roll_number,
            college=college,
            department=department,
            semester=semester,
            student_id=student_id,
            email=email,
            phone=phone,
            photo1_path=photo1_path,
            photo2_path=photo2_path,
            photo3_path=photo3_path,
        )

        db.session.add(student)

        # Get student.id
        db.session.flush()

        # Generate face encoding
        image_paths = [
            p
            for p in [
                photo1_path,
                photo2_path,
                photo3_path
            ]
            if p
        ]

        enc_path = face_service.save_student_encoding(
            student_id=student.id,
            roll_number=roll_number,
            image_paths=image_paths,
            face_data_folder=current_app.config[
                "FACE_DATA_FOLDER"
            ],
        )

        student.face_encoding_path = enc_path

        db.session.commit()

        if enc_path:

            flash(
                f"Student '{full_name}' registered "
                f"and face encoded successfully!",
                "success"
            )

        else:

            flash(
                f"Student '{full_name}' registered, "
                f"but face encoding failed "
                f"(ensure photos show a clear face).",
                "warning"
            )

        return redirect(
            url_for(
                "student.detail",
                student_id=student.id
            )
        )

    return render_template(
        "student/register.html"
    )


# ---------------------------------------------------------------------------
# Student detail
# ---------------------------------------------------------------------------

@student_bp.route("/<int:student_id>")
@login_required
def detail(student_id: int):

    student = Student.query.get_or_404(student_id)

    from app.models import AttendanceRecord, AttendanceSession

    records = (
        AttendanceRecord.query
        .filter_by(student_id=student_id)
        .join(AttendanceSession)
        .order_by(AttendanceSession.date.desc())
        .limit(20)
        .all()
    )

    total = len(records)

    present = sum(
        1
        for r in records
        if r.status == "Present"
    )

    absent = total - present

    pct = (
        round((present / total) * 100)
        if total > 0
        else 0
    )

    return render_template(
        "student/detail.html",
        student=student,
        records=records,
        total=total,
        present=present,
        absent=absent,
        pct=pct,
    )


# ---------------------------------------------------------------------------
# Edit student
# ---------------------------------------------------------------------------

@student_bp.route(
    "/<int:student_id>/edit",
    methods=["GET", "POST"]
)
@login_required
def edit(student_id: int):

    student = Student.query.get_or_404(student_id)

    if request.method == "POST":

        student.full_name = (
            request.form.get(
                "full_name",
                student.full_name
            ).strip()
        )

        student.college = (
            request.form.get(
                "college",
                student.college or ""
            ).strip()
        )

        student.department = (
            request.form.get(
                "department",
                student.department or ""
            ).strip()
        )

        student.semester = (
            request.form.get(
                "semester",
                student.semester or ""
            ).strip()
        )

        student.student_id = (
            request.form.get(
                "student_id",
                student.student_id or ""
            ).strip()
        )

        student.email = (
            request.form.get(
                "email",
                student.email or ""
            ).strip()
        )

        student.phone = (
            request.form.get(
                "phone",
                student.phone or ""
            ).strip()
        )

        # Handle new photos
        for idx, key in enumerate(
            ["photo1", "photo2", "photo3"],
            start=1
        ):

            f = request.files.get(key)

            if f and f.filename:

                path = _save_photo(
                    f,
                    student.roll_number,
                    f"photo{idx}"
                )

                if path:

                    setattr(
                        student,
                        f"photo{idx}_path",
                        path
                    )

        db.session.commit()

        # Re-encode face if photos changed
        image_paths = [
            p
            for p in student.photo_paths
            if p
        ]

        if image_paths:

            enc_path = face_service.save_student_encoding(
                student_id=student.id,
                roll_number=student.roll_number,
                image_paths=image_paths,
                face_data_folder=current_app.config[
                    "FACE_DATA_FOLDER"
                ],
            )

            if enc_path:

                student.face_encoding_path = enc_path

                db.session.commit()

        flash(
            "Student updated successfully.",
            "success"
        )

        return redirect(
            url_for(
                "student.detail",
                student_id=student.id
            )
        )

    return render_template(
        "student/edit.html",
        student=student
    )


# ---------------------------------------------------------------------------
# Delete student (soft delete)
# ---------------------------------------------------------------------------

@student_bp.route(
    "/<int:student_id>/delete",
    methods=["POST"]
)
@login_required
def delete(student_id: int):

    student = Student.query.get_or_404(student_id)

    student.is_active = False

    db.session.commit()

    flash(
        f"Student '{student.full_name}' has been removed.",
        "info"
    )

    return redirect(
        url_for("student.list_students")
    )


# ---------------------------------------------------------------------------
# API – return photo path as relative URL
# ---------------------------------------------------------------------------

@student_bp.route(
    "/api/photo/<path:photo_path>"
)
@login_required
def serve_photo(photo_path):

    """Return photo path as JSON."""

    return jsonify({
        "path": photo_path
    })