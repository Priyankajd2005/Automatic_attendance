"""
app/routes/auth.py
------------------
Teacher authentication: login, logout, register, profile.
"""

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, current_app
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash

from app import db
from app.models import Teacher

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Teacher login page."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        teacher = Teacher.query.filter_by(username=username).first()

        if teacher and teacher.check_password(password):
            login_user(teacher, remember=remember)
            next_page = request.args.get("next")
            flash(f"Welcome back, {teacher.full_name}!", "success")
            return redirect(next_page or url_for("dashboard.index"))
        else:
            flash("Invalid username or password. Please try again.", "danger")

    return render_template("auth/login.html")


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@auth_bp.route("/logout")
@login_required
def logout():
    """Log the current teacher out."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Register a new teacher account."""
    if request.method == "POST":
        username  = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        college   = request.form.get("college", "").strip()
        password  = request.form.get("password", "")
        confirm   = request.form.get("confirm_password", "")

        # Validation
        if not username or not full_name or not password:
            flash("All required fields must be filled.", "danger")
            return render_template("auth/register.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("auth/register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("auth/register.html")

        if Teacher.query.filter_by(username=username).first():
            flash("Username already taken. Choose a different one.", "warning")
            return render_template("auth/register.html")

        teacher = Teacher(username=username, full_name=full_name, college=college)
        teacher.set_password(password)
        db.session.add(teacher)
        db.session.commit()

        flash("Account created! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """View / update teacher profile."""
    if request.method == "POST":
        current_user.full_name = request.form.get("full_name", current_user.full_name).strip()
        current_user.college   = request.form.get("college", current_user.college or "").strip()

        new_password = request.form.get("new_password", "")
        if new_password:
            if len(new_password) < 6:
                flash("New password must be at least 6 characters.", "danger")
                return render_template("auth/profile.html")
            current_user.set_password(new_password)
            flash("Password updated.", "success")

        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("auth.profile"))

    return render_template("auth/profile.html")
