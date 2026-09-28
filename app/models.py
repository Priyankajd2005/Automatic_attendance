"""
app/models.py
-------------
SQLAlchemy ORM models for the Automatic Attendance Management System.

Models
------
Teacher           – system user (logs in, takes attendance)
Student           – registered student with face data
Subject           – academic subject / course
AttendanceSession – one attendance-taking event (single class period)
AttendanceRecord  – one student's status within a session
"""

from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db


# ---------------------------------------------------------------------------
# Teacher
# ---------------------------------------------------------------------------

class Teacher(db.Model, UserMixin):
    """
    Represents a teaching staff member who can log in and manage attendance.
    Inherits UserMixin to provide the Flask-Login interface
    (is_authenticated, is_active, get_id, etc.).
    """

    __tablename__ = "teacher"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    college = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationship: sessions created by this teacher
    sessions = db.relationship(
        "AttendanceSession", back_populates="teacher", lazy="dynamic"
    )

    def set_password(self, password: str) -> None:
        """Hash and store the given plaintext password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Return True if the plaintext password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<Teacher {self.username!r}>"


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------

class Student(db.Model):
    """
    Represents a student enrolled in the system.
    Up to three face photos are stored together with the averaged
    128-dimensional face encoding in a .npy file.
    """

    __tablename__ = "student"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    college = db.Column(db.String(200), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    semester = db.Column(db.String(20), nullable=True)
    student_id = db.Column(db.String(50), nullable=True)  # institution-specific ID
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(20), nullable=True)

    # Paths to the three uploaded face photos (relative to UPLOAD_FOLDER)
    photo1_path = db.Column(db.String(300), nullable=True)
    photo2_path = db.Column(db.String(300), nullable=True)
    photo3_path = db.Column(db.String(300), nullable=True)

    # Path to the averaged face encoding file (.npy) in FACE_DATA_FOLDER
    face_encoding_path = db.Column(db.String(300), nullable=True)

    # Optional: Google Form ID used during bulk import
    google_form_id = db.Column(db.String(100), nullable=True)

    registered_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Relationship: all attendance records for this student
    attendances = db.relationship(
        "AttendanceRecord", back_populates="student", lazy="dynamic"
    )

    @property
    def photo_paths(self) -> list:
        """Return a list of non-null photo paths for this student."""
        return [p for p in (self.photo1_path, self.photo2_path, self.photo3_path) if p]

    def attendance_percentage(self, subject_id: int = None) -> float:
        """
        Calculate overall (or subject-specific) attendance percentage.

        Parameters
        ----------
        subject_id : int, optional
            Filter to a specific subject. If None, all subjects are included.

        Returns
        -------
        float
            Percentage of 'Present' records out of total records (0.0 – 100.0).
        """
        query = self.attendances.join(AttendanceSession)
        if subject_id is not None:
            query = query.filter(AttendanceSession.subject_id == subject_id)
        total = query.count()
        if total == 0:
            return 0.0
        present = query.filter(AttendanceRecord.status == "Present").count()
        return round((present / total) * 100, 2)

    def __repr__(self) -> str:
        return f"<Student {self.roll_number!r} – {self.full_name!r}>"


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------

class Subject(db.Model):
    """Academic subject or course taught by teachers."""

    __tablename__ = "subject"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(30), nullable=True)
    college = db.Column(db.String(200), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    semester = db.Column(db.String(20), nullable=True)

    # Relationship: attendance sessions for this subject
    sessions = db.relationship(
        "AttendanceSession", back_populates="subject", lazy="dynamic"
    )

    def __repr__(self) -> str:
        return f"<Subject {self.code!r} – {self.name!r}>"


# ---------------------------------------------------------------------------
# AttendanceSession
# ---------------------------------------------------------------------------

class AttendanceSession(db.Model):
    """
    Represents a single class period in which attendance was taken.
    One classroom photograph is associated with the session; face recognition
    runs against that photograph to generate AttendanceRecord rows.
    """

    __tablename__ = "attendance_session"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id"), nullable=False)
    college = db.Column(db.String(200), nullable=True)
    department = db.Column(db.String(100), nullable=True)
    semester = db.Column(db.String(20), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=True)
    date = db.Column(db.Date, default=date.today, nullable=False)
    period = db.Column(db.String(30), nullable=True)  # e.g. "Period 1", "9:00–10:00"
    classroom_photo_path = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Once finalized the teacher cannot make further edits
    is_finalized = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    teacher = db.relationship("Teacher", back_populates="sessions")
    subject = db.relationship("Subject", back_populates="sessions")
    records = db.relationship(
        "AttendanceRecord",
        back_populates="session",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    @property
    def present_count(self) -> int:
        """Number of students marked Present in this session."""
        return self.records.filter_by(status="Present").count()

    @property
    def absent_count(self) -> int:
        """Number of students marked Absent in this session."""
        return self.records.filter_by(status="Absent").count()

    @property
    def total_count(self) -> int:
        """Total number of attendance records for this session."""
        return self.records.count()

    def __repr__(self) -> str:
        return (
            f"<AttendanceSession id={self.id} date={self.date} "
            f"dept={self.department!r}>"
        )


# ---------------------------------------------------------------------------
# AttendanceRecord
# ---------------------------------------------------------------------------

class AttendanceRecord(db.Model):
    """
    A single student's attendance status within one AttendanceSession.

    status choices:
      'Present'  – face was recognised or teacher manually marked present
      'Absent'   – not detected / manually marked absent
      'Unknown'  – face detected but not matched to any known student

    marked_by choices:
      'auto'    – set by the face-recognition pipeline
      'manual'  – overridden by the teacher during review
    """

    __tablename__ = "attendance_record"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("attendance_session.id"), nullable=False
    )
    student_id = db.Column(
        db.Integer, db.ForeignKey("student.id"), nullable=True
    )  # NULL when status == 'Unknown'
    status = db.Column(
        db.String(20),
        nullable=False,
        default="Absent",
    )  # 'Present' | 'Absent' | 'Unknown'
    confidence_score = db.Column(db.Float, nullable=True)
    marked_by = db.Column(db.String(10), nullable=False, default="auto")  # 'auto' | 'manual'
    notes = db.Column(db.Text, nullable=True)

    # Relationships
    session = db.relationship("AttendanceSession", back_populates="records")
    student = db.relationship("Student", back_populates="attendances")

    def __repr__(self) -> str:
        return (
            f"<AttendanceRecord session={self.session_id} "
            f"student={self.student_id} status={self.status!r}>"
        )
