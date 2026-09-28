"""
app/routes/attendance.py
-------------------------
Attendance workflow:
  1. Teacher fills session form + uploads classroom photo -> /attendance/new
  2. System runs face recognition -> /attendance/process/<id>  (POST, JSON)
  3. Teacher reviews & corrects   -> /attendance/verify/<id>
  4. Teacher confirms             -> /attendance/verify/<id>/save (POST)
  5. History & session details
"""

import os
import json
import uuid
from datetime import date, datetime
from pathlib import Path

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, current_app, jsonify
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from app.models import (
    Student, Subject, AttendanceSession, AttendanceRecord, Teacher
)
from app.services import face_service

attendance_bp = Blueprint("attendance", __name__, url_prefix="/attendance")

ALLOWED = {"png", "jpg", "jpeg", "webp"}


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED


# ---------------------------------------------------------------------------
# New attendance session
# ---------------------------------------------------------------------------

@attendance_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_session():
    """Form: select class details + upload classroom photo."""
    subjects = Subject.query.order_by(Subject.name).all()

    if request.method == "POST":
        college    = request.form.get("college", "").strip()
        department = request.form.get("department", "").strip()
        semester   = request.form.get("semester", "").strip()
        subject_id = request.form.get("subject_id") or None
        period     = request.form.get("period", "").strip()
        date_str   = request.form.get("date", "")

        # Parse date
        try:
            session_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            session_date = date.today()

        # Save classroom photo
        photo_file = request.files.get("classroom_photo")
        if not photo_file or photo_file.filename == "":
            flash("Please upload a classroom photograph.", "danger")
            return render_template("attendance/new.html", subjects=subjects)

        if not _allowed(photo_file.filename):
            flash("Only image files (jpg, png, jpeg) are allowed.", "danger")
            return render_template("attendance/new.html", subjects=subjects)

        ext = photo_file.filename.rsplit(".", 1)[1].lower()
        photo_filename = f"classroom_{uuid.uuid4().hex}.{ext}"
        classroom_folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "classroom")
        os.makedirs(classroom_folder, exist_ok=True)
        photo_path = os.path.join(classroom_folder, photo_filename)
        photo_file.save(photo_path)

        # Create session record
        session = AttendanceSession(
            teacher_id=current_user.id,
            college=college,
            department=department,
            semester=semester,
            subject_id=int(subject_id) if subject_id else None,
            date=session_date,
            period=period,
            classroom_photo_path=photo_path,
        )
        db.session.add(session)
        db.session.commit()

        flash("Classroom photo uploaded. Processing face recognition...", "info")
        return redirect(url_for("attendance.verify_session", session_id=session.id))

    return render_template("attendance/new.html", subjects=subjects, today=date.today().isoformat())


# ---------------------------------------------------------------------------
# Process face recognition (called from verify page via JS or direct redirect)
# ---------------------------------------------------------------------------

@attendance_bp.route("/process/<int:session_id>", methods=["GET", "POST"])
@login_required
def process_session(session_id: int):
    """
    Run face recognition on the classroom photo.
    Populates AttendanceRecord rows (auto-marked).
    Returns JSON if POST (called by JS), or redirects to verify if GET.
    """
    session = AttendanceSession.query.get_or_404(session_id)

    if session.is_finalized:
        data = {"success": False, "error": "Session already finalized."}
        return jsonify(data) if request.method == "POST" else redirect(
            url_for("attendance.session_detail", session_id=session_id)
        )

    # Load known encodings (filter by dept + semester for speed)
    known = face_service.load_all_encodings(
        face_data_folder=current_app.config["FACE_DATA_FOLDER"],
        department=session.department,
        semester=session.semester,
    )

    tolerance = float(current_app.config.get("FACE_RECOGNITION_TOLERANCE", 0.5))
    results = face_service.recognize_faces_in_image(
        classroom_image_path=session.classroom_photo_path,
        known_encodings=known,
        tolerance=tolerance,
    )

    # Draw annotated photo
    annotated_folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "annotated")
    annotated_path = face_service.draw_boxes_on_image(
        image_path=session.classroom_photo_path,
        recognition_results=results,
        output_folder=annotated_folder,
    )

    # ---- Build attendance records ----
    # Delete any existing auto-records for this session
    AttendanceRecord.query.filter_by(session_id=session.id).delete()
    db.session.flush()

    # Get all students for this dept/semester
    student_query = Student.query.filter_by(is_active=True)
    if session.department:
        student_query = student_query.filter(Student.department.ilike(f"%{session.department}%"))
    if session.semester:
        student_query = student_query.filter_by(semester=session.semester)
    all_students = {s.roll_number: s for s in student_query.all()}

    recognized_rolls = set()
    for face in results:
        if face["status"] == "recognized" and face["roll_number"]:
            recognized_rolls.add(face["roll_number"])
            student = all_students.get(face["roll_number"])
            if student:
                record = AttendanceRecord(
                    session_id=session.id,
                    student_id=student.id,
                    status="Present",
                    confidence_score=face.get("confidence"),
                    marked_by="auto",
                )
                db.session.add(record)

    # Mark undetected students as Absent
    for roll, student in all_students.items():
        if roll not in recognized_rolls:
            record = AttendanceRecord(
                session_id=session.id,
                student_id=student.id,
                status="Absent",
                confidence_score=None,
                marked_by="auto",
            )
            db.session.add(record)

    # Add Unknown face records (no student_id)
    for face in results:
        if face["status"] == "unknown":
            record = AttendanceRecord(
                session_id=session.id,
                student_id=None,
                status="Unknown",
                confidence_score=face.get("confidence"),
                marked_by="auto",
                notes=f"Unrecognized face detected in classroom photo.",
            )
            db.session.add(record)

    # Save annotated path to session
    if annotated_path:
        session.classroom_photo_path = annotated_path

    db.session.commit()

    response_data = {
        "success": True,
        "session_id": session.id,
        "recognized": len(recognized_rolls),
        "absent": len(all_students) - len(recognized_rolls),
        "unknown": sum(1 for r in results if r["status"] == "unknown"),
        "recognition_results": [
            {
                "location": list(r["location"]),
                "roll_number": r.get("roll_number"),
                "name": r.get("name"),
                "confidence": r.get("confidence", 0.0),
                "status": r["status"],
            }
            for r in results
        ],
    }

    if request.method == "POST":
        return jsonify(response_data)

    return redirect(url_for("attendance.verify_session", session_id=session.id))


# ---------------------------------------------------------------------------
# Verify / review attendance
# ---------------------------------------------------------------------------

@attendance_bp.route("/verify/<int:session_id>")
@login_required
def verify_session(session_id: int):
    """Show annotated photo + editable attendance table for review."""
    session = AttendanceSession.query.get_or_404(session_id)

    # If not yet processed, process now
    existing_records = AttendanceRecord.query.filter_by(session_id=session.id).count()
    if existing_records == 0:
        return redirect(url_for("attendance.process_session", session_id=session_id))

    records = (
        AttendanceRecord.query
        .filter_by(session_id=session.id)
        .filter(AttendanceRecord.student_id.isnot(None))
        .join(Student)
        .order_by(Student.roll_number)
        .all()
    )
    unknown_records = (
        AttendanceRecord.query
        .filter_by(session_id=session.id, student_id=None)
        .all()
    )

    present_count = sum(1 for r in records if r.status == "Present")
    absent_count  = sum(1 for r in records if r.status == "Absent")

    # Build relative photo URL
    photo_url = None
    if session.classroom_photo_path and os.path.exists(session.classroom_photo_path):
        rel = os.path.relpath(
            session.classroom_photo_path,
            os.path.join(current_app.root_path, "static")
        )
        photo_url = url_for("static", filename=rel.replace("\\", "/"))

    return render_template(
        "attendance/verify.html",
        session=session,
        records=records,
        unknown_records=unknown_records,
        present_count=present_count,
        absent_count=absent_count,
        total_count=len(records),
        photo_url=photo_url,
    )


# ---------------------------------------------------------------------------
# Save finalized attendance
# ---------------------------------------------------------------------------

@attendance_bp.route("/verify/<int:session_id>/save", methods=["POST"])
@login_required
def save_attendance(session_id: int):
    """Apply teacher corrections and finalize attendance."""
    session = AttendanceSession.query.get_or_404(session_id)

    if session.is_finalized:
        flash("This session has already been finalized.", "warning")
        return redirect(url_for("attendance.session_detail", session_id=session_id))

    records = AttendanceRecord.query.filter_by(session_id=session.id).all()

    for record in records:
        if record.student_id is None:
            continue
        key = f"status_{record.student_id}"
        new_status = request.form.get(key)
        if new_status in ("Present", "Absent") and new_status != record.status:
            record.status    = new_status
            record.marked_by = "manual"

    session.is_finalized = True
    db.session.commit()

    flash(
        f"Attendance saved! "
        f"{session.present_count} present, {session.absent_count} absent.",
        "success",
    )
    return redirect(url_for("attendance.session_detail", session_id=session_id))


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@attendance_bp.route("/history")
@login_required
def history():
    """List all attendance sessions."""
    dept     = request.args.get("department", "")
    semester = request.args.get("semester", "")
    date_str = request.args.get("date", "")

    query = AttendanceSession.query.filter_by(teacher_id=current_user.id)
    if dept:
        query = query.filter(AttendanceSession.department.ilike(f"%{dept}%"))
    if semester:
        query = query.filter_by(semester=semester)
    if date_str:
        try:
            filter_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            query = query.filter_by(date=filter_date)
        except ValueError:
            pass

    sessions = query.order_by(AttendanceSession.date.desc(), AttendanceSession.created_at.desc()).all()
    return render_template("attendance/history.html", sessions=sessions)


# ---------------------------------------------------------------------------
# Session detail
# ---------------------------------------------------------------------------

@attendance_bp.route("/session/<int:session_id>")
@login_required
def session_detail(session_id: int):
    """Read-only view of a finalized session."""
    session = AttendanceSession.query.get_or_404(session_id)
    records = (
        AttendanceRecord.query
        .filter_by(session_id=session.id)
        .filter(AttendanceRecord.student_id.isnot(None))
        .join(Student)
        .order_by(Student.roll_number)
        .all()
    )
    unknown_records = AttendanceRecord.query.filter_by(
        session_id=session.id, student_id=None
    ).all()

    photo_url = None
    if session.classroom_photo_path and os.path.exists(session.classroom_photo_path):
        try:
            rel = os.path.relpath(
                session.classroom_photo_path,
                os.path.join(current_app.root_path, "static")
            )
            photo_url = url_for("static", filename=rel.replace("\\", "/"))
        except Exception:
            pass

    return render_template(
        "attendance/session_detail.html",
        session=session,
        records=records,
        unknown_records=unknown_records,
        photo_url=photo_url,
    )


# ---------------------------------------------------------------------------
# API – subjects for a dept/semester
# ---------------------------------------------------------------------------

@attendance_bp.route("/api/subjects")
@login_required
def api_subjects():
    dept     = request.args.get("department", "")
    semester = request.args.get("semester", "")
    query = Subject.query
    if dept:
        query = query.filter(Subject.department.ilike(f"%{dept}%"))
    if semester:
        query = query.filter_by(semester=semester)
    subjects = query.order_by(Subject.name).all()
    return jsonify([{"id": s.id, "name": s.name, "code": s.code} for s in subjects])
