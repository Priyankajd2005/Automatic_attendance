"""
app/routes/dashboard.py
------------------------
Analytics dashboard: overview, student reports, subject reports,
date-wise reports, and CSV export.
"""

import csv
import io
from datetime import date, datetime, timedelta

from flask import (
    Blueprint, render_template, request, jsonify,
    Response, redirect, url_for, flash, current_app
)
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.models import (
    Student, Subject, AttendanceSession, AttendanceRecord, Teacher
)

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------

@dashboard_bp.route("/")
@login_required
def index():
    """Main dashboard overview."""
    today = date.today()

    # --- Stats ---
    total_students  = Student.query.filter_by(is_active=True).count()
    today_sessions  = AttendanceSession.query.filter_by(date=today).count()

    present_today = (
        db.session.query(func.count(AttendanceRecord.id))
        .join(AttendanceSession)
        .filter(AttendanceSession.date == today, AttendanceRecord.status == "Present")
        .scalar() or 0
    )
    absent_today = (
        db.session.query(func.count(AttendanceRecord.id))
        .join(AttendanceSession)
        .filter(AttendanceSession.date == today, AttendanceRecord.status == "Absent")
        .scalar() or 0
    )

    # --- Recent sessions (last 10) ---
    recent_sessions = (
        AttendanceSession.query
        .order_by(AttendanceSession.date.desc(), AttendanceSession.created_at.desc())
        .limit(10)
        .all()
    )

    # --- Last 7-day attendance chart data ---
    chart_labels = []
    chart_present = []
    chart_absent  = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        chart_labels.append(d.strftime("%d %b"))
        p = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(AttendanceSession)
            .filter(AttendanceSession.date == d, AttendanceRecord.status == "Present")
            .scalar() or 0
        )
        a = (
            db.session.query(func.count(AttendanceRecord.id))
            .join(AttendanceSession)
            .filter(AttendanceSession.date == d, AttendanceRecord.status == "Absent")
            .scalar() or 0
        )
        chart_present.append(p)
        chart_absent.append(a)

    # --- Dept-wise student count ---
    dept_data = (
        db.session.query(Student.department, func.count(Student.id))
        .filter_by(is_active=True)
        .group_by(Student.department)
        .all()
    )
    dept_labels = [d[0] or "Unknown" for d in dept_data]
    dept_counts  = [d[1] for d in dept_data]

    return render_template(
        "dashboard/index.html",
        total_students=total_students,
        today_sessions=today_sessions,
        present_today=present_today,
        absent_today=absent_today,
        recent_sessions=recent_sessions,
        chart_labels=chart_labels,
        chart_present=chart_present,
        chart_absent=chart_absent,
        dept_labels=dept_labels,
        dept_counts=dept_counts,
        today=today,
    )


# ---------------------------------------------------------------------------
# Student-wise report
# ---------------------------------------------------------------------------

@dashboard_bp.route("/student/<string:roll_number>")
@login_required
def student_report(roll_number: str):
    student = Student.query.filter_by(roll_number=roll_number.upper()).first_or_404()

    # All records
    all_records = (
        AttendanceRecord.query
        .filter_by(student_id=student.id)
        .join(AttendanceSession)
        .order_by(AttendanceSession.date.desc())
        .all()
    )

    total   = len(all_records)
    present = sum(1 for r in all_records if r.status == "Present")
    absent  = total - present
    pct     = round((present / total) * 100) if total else 0

    # Subject-wise breakdown
    subject_data = (
        db.session.query(
            Subject.name,
            func.count(AttendanceRecord.id).label("total"),
            func.sum(
                db.case((AttendanceRecord.status == "Present", 1), else_=0)
            ).label("present"),
        )
        .join(AttendanceSession, AttendanceSession.subject_id == Subject.id)
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .filter(AttendanceRecord.student_id == student.id)
        .group_by(Subject.id)
        .all()
    )

    return render_template(
        "dashboard/student_report.html",
        student=student,
        all_records=all_records,
        total=total,
        present=present,
        absent=absent,
        pct=pct,
        subject_data=subject_data,
    )


# ---------------------------------------------------------------------------
# Subject-wise report
# ---------------------------------------------------------------------------

@dashboard_bp.route("/subject/<int:subject_id>")
@login_required
def subject_report(subject_id: int):
    subject = Subject.query.get_or_404(subject_id)

    sessions = (
        AttendanceSession.query
        .filter_by(subject_id=subject_id)
        .order_by(AttendanceSession.date.desc())
        .all()
    )

    # Per-session summary
    session_summaries = []
    for s in sessions:
        session_summaries.append({
            "session": s,
            "present": s.present_count,
            "absent":  s.absent_count,
            "total":   s.total_count,
            "pct":     round((s.present_count / s.total_count) * 100) if s.total_count else 0,
        })

    return render_template(
        "dashboard/subject_report.html",
        subject=subject,
        session_summaries=session_summaries,
    )


# ---------------------------------------------------------------------------
# Filterable report
# ---------------------------------------------------------------------------

@dashboard_bp.route("/report")
@login_required
def report():
    """Filterable attendance report across all sessions."""
    dept       = request.args.get("department", "")
    semester   = request.args.get("semester", "")
    subject_id = request.args.get("subject_id", "")
    date_from  = request.args.get("date_from", "")
    date_to    = request.args.get("date_to", "")
    roll       = request.args.get("roll", "").strip().upper()
    status     = request.args.get("status", "")

    query = (
        AttendanceRecord.query
        .join(AttendanceSession)
        .join(Student, AttendanceRecord.student_id == Student.id, isouter=True)
    )

    if dept:
        query = query.filter(AttendanceSession.department.ilike(f"%{dept}%"))
    if semester:
        query = query.filter(AttendanceSession.semester == semester)
    if subject_id:
        query = query.filter(AttendanceSession.subject_id == int(subject_id))
    if date_from:
        try:
            query = query.filter(AttendanceSession.date >= datetime.strptime(date_from, "%Y-%m-%d").date())
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(AttendanceSession.date <= datetime.strptime(date_to, "%Y-%m-%d").date())
        except ValueError:
            pass
    if roll:
        query = query.filter(Student.roll_number.ilike(f"%{roll}%"))
    if status:
        query = query.filter(AttendanceRecord.status == status)

    records = query.order_by(AttendanceSession.date.desc()).limit(500).all()

    subjects     = Subject.query.order_by(Subject.name).all()
    departments  = [r[0] for r in db.session.query(Student.department).distinct().all() if r[0]]
    semesters    = [r[0] for r in db.session.query(Student.semester).distinct().all() if r[0]]

    return render_template(
        "dashboard/report.html",
        records=records,
        subjects=subjects,
        departments=departments,
        semesters=semesters,
        filters={
            "department": dept, "semester": semester,
            "subject_id": subject_id, "date_from": date_from,
            "date_to": date_to, "roll": roll, "status": status,
        },
    )


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

@dashboard_bp.route("/export")
@login_required
def export_csv():
    """Export filtered attendance as CSV."""
    dept       = request.args.get("department", "")
    semester   = request.args.get("semester", "")
    subject_id = request.args.get("subject_id", "")
    date_from  = request.args.get("date_from", "")
    date_to    = request.args.get("date_to", "")

    query = (
        db.session.query(
            Student.roll_number,
            Student.full_name,
            Student.department,
            Student.semester,
            AttendanceSession.date,
            AttendanceSession.period,
            Subject.name.label("subject"),
            AttendanceRecord.status,
            AttendanceRecord.marked_by,
            AttendanceRecord.confidence_score,
        )
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .join(Student, AttendanceRecord.student_id == Student.id)
        .outerjoin(Subject, AttendanceSession.subject_id == Subject.id)
    )

    if dept:
        query = query.filter(AttendanceSession.department.ilike(f"%{dept}%"))
    if semester:
        query = query.filter(AttendanceSession.semester == semester)
    if subject_id:
        query = query.filter(AttendanceSession.subject_id == int(subject_id))
    if date_from:
        try:
            query = query.filter(
                AttendanceSession.date >= datetime.strptime(date_from, "%Y-%m-%d").date()
            )
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(
                AttendanceSession.date <= datetime.strptime(date_to, "%Y-%m-%d").date()
            )
        except ValueError:
            pass

    rows = query.order_by(AttendanceSession.date.desc(), Student.roll_number).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Roll Number", "Full Name", "Department", "Semester",
        "Date", "Period", "Subject", "Status", "Marked By", "Confidence"
    ])
    for row in rows:
        writer.writerow([
            row.roll_number, row.full_name, row.department, row.semester,
            row.date, row.period or "-", row.subject or "-",
            row.status, row.marked_by,
            f"{row.confidence_score:.2f}" if row.confidence_score else "-",
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=attendance_report.csv"},
    )
