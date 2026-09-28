"""
app/services/google_service.py
--------------------------------
Handles all Google API interactions:
  - Authenticating with a service-account credentials file
  - Fetching form responses from Google Sheets
  - Downloading student photos from Google Drive
  - Syncing new students into the local database

Usage
-----
Set GOOGLE_CREDENTIALS_FILE and GOOGLE_SPREADSHEET_ID in .env,
then call sync_students_from_sheet() from the /admin/sync route.
"""

import os
import io
import re
import logging
import json
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Optional Google API imports – degrade gracefully
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False
    logger.warning(
        "google-api-python-client not installed. "
        "Google Sheets sync will be unavailable."
    )

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def _get_credentials(credentials_file: str):
    """Return Google service-account credentials, or None on failure."""
    if not GOOGLE_AVAILABLE:
        return None
    path = Path(credentials_file)
    if not path.exists():
        logger.error("Google credentials file not found: %s", credentials_file)
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            str(path), scopes=SCOPES
        )
        return creds
    except Exception as exc:
        logger.error("Failed to load Google credentials: %s", exc)
        return None


def _get_sheets_service(credentials_file: str):
    creds = _get_credentials(credentials_file)
    if creds is None:
        return None
    return build("sheets", "v4", credentials=creds)


def _get_drive_service(credentials_file: str):
    creds = _get_credentials(credentials_file)
    if creds is None:
        return None
    return build("drive", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Sheet helpers
# ---------------------------------------------------------------------------

def get_form_responses(
    spreadsheet_id: str,
    credentials_file: str,
    sheet_name: str = "Form Responses 1",
) -> list:
    """
    Fetch all rows from a Google Sheet as a list of row lists.

    Returns
    -------
    list[list]
        Each inner list is one row (including the header row as row 0).
    """
    service = _get_sheets_service(credentials_file)
    if service is None:
        return []
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_name)
            .execute()
        )
        rows = result.get("values", [])
        logger.info("Fetched %d rows from sheet '%s'", len(rows), sheet_name)
        return rows
    except Exception as exc:
        logger.error("get_form_responses error: %s", exc)
        return []


def rows_to_dicts(rows: list) -> list:
    """Convert a list-of-lists (header + data rows) into list-of-dicts."""
    if not rows or len(rows) < 2:
        return []
    headers = rows[0]
    result = []
    for row in rows[1:]:
        # Pad short rows with empty strings
        padded = row + [""] * (len(headers) - len(row))
        result.append(dict(zip(headers, padded)))
    return result


# ---------------------------------------------------------------------------
# Drive photo download
# ---------------------------------------------------------------------------

def _extract_drive_file_id(url_or_id: str) -> Optional[str]:
    """
    Extract the Google Drive file ID from a sharing URL or return the
    raw ID if it doesn't look like a URL.

    Supported URL formats
    ---------------------
    - https://drive.google.com/file/d/<ID>/view?...
    - https://drive.google.com/open?id=<ID>
    - https://docs.google.com/...?id=<ID>
    """
    if not url_or_id:
        return None
    # Already a plain file ID (no slashes / dots common in URLs)
    if "/" not in url_or_id and "." not in url_or_id:
        return url_or_id
    # /file/d/<ID>/
    m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url_or_id)
    if m:
        return m.group(1)
    # ?id=<ID>
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url_or_id)
    if m:
        return m.group(1)
    return None


def download_drive_photo(
    url_or_id: str,
    save_path: str,
    credentials_file: str,
) -> Optional[str]:
    """
    Download a file from Google Drive and save it locally.

    Tries the Drive API first; falls back to a direct export URL for
    publicly shared files.

    Returns the save_path on success, None on failure.
    """
    file_id = _extract_drive_file_id(url_or_id)
    if not file_id:
        logger.warning("Could not extract Drive file ID from: %s", url_or_id)
        return None

    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # --- Try Drive API ---
    if GOOGLE_AVAILABLE:
        service = _get_drive_service(credentials_file)
        if service:
            try:
                request = service.files().get_media(fileId=file_id)
                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                with open(save_path, "wb") as f:
                    f.write(buf.getvalue())
                logger.info("Downloaded Drive file %s -> %s", file_id, save_path)
                return save_path
            except Exception as exc:
                logger.warning("Drive API download failed (%s), trying direct URL.", exc)

    # --- Fallback: direct export URL (works for publicly shared files) ---
    try:
        direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        resp = requests.get(direct_url, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 1000:
            with open(save_path, "wb") as f:
                f.write(resp.content)
            logger.info("Downloaded Drive file via direct URL -> %s", save_path)
            return save_path
    except Exception as exc:
        logger.error("Direct Drive download failed: %s", exc)

    return None


# ---------------------------------------------------------------------------
# High-level sync
# ---------------------------------------------------------------------------

def sync_students_from_sheet(
    spreadsheet_id: str,
    credentials_file: str,
    column_mapping: dict,
    photo_save_dir: str,
    sheet_name: str = "Form Responses 1",
) -> dict:
    """
    Fetch rows from a Google Sheet and map them to student data dicts.

    Parameters
    ----------
    spreadsheet_id : str
    credentials_file : str
    column_mapping : dict
        Maps student fields -> sheet column headers.
        Example::

            {
                "full_name":   "Full Name",
                "roll_number": "Roll Number",
                "college":     "College Name",
                "department":  "Department",
                "semester":    "Semester",
                "student_id":  "Student ID",
                "email":       "Email Address",
                "phone":       "Phone Number",
                "photo1":      "Front Photo",
                "photo2":      "Left Side Photo",
                "photo3":      "Right Side Photo",
            }
    photo_save_dir : str
        Local directory to save downloaded photos.
    sheet_name : str
        Tab name in the spreadsheet.

    Returns
    -------
    dict
        ``{'students': list[dict], 'errors': list[str], 'total': int}``
    """
    rows = get_form_responses(spreadsheet_id, credentials_file, sheet_name)
    if not rows:
        return {"students": [], "errors": ["No data found in sheet."], "total": 0}

    row_dicts = rows_to_dicts(rows)
    students = []
    errors = []

    for i, row in enumerate(row_dicts, start=2):  # row 2 = first data row in Sheets
        roll = row.get(column_mapping.get("roll_number", ""), "").strip()
        if not roll:
            errors.append(f"Row {i}: missing roll number, skipped.")
            continue

        student_data = {
            "full_name":   row.get(column_mapping.get("full_name", ""), "").strip(),
            "roll_number": roll,
            "college":     row.get(column_mapping.get("college", ""), "").strip(),
            "department":  row.get(column_mapping.get("department", ""), "").strip(),
            "semester":    row.get(column_mapping.get("semester", ""), "").strip(),
            "student_id":  row.get(column_mapping.get("student_id", ""), "").strip(),
            "email":       row.get(column_mapping.get("email", ""), "").strip(),
            "phone":       row.get(column_mapping.get("phone", ""), "").strip(),
            "photo1_path": None,
            "photo2_path": None,
            "photo3_path": None,
        }

        # Download photos
        for photo_key, local_key in [("photo1", "photo1_path"), ("photo2", "photo2_path"), ("photo3", "photo3_path")]:
            url = row.get(column_mapping.get(photo_key, ""), "").strip()
            if url:
                ext = ".jpg"
                local_name = f"{roll}_{photo_key}{ext}"
                local_path = os.path.join(photo_save_dir, local_name)
                result = download_drive_photo(url, local_path, credentials_file)
                if result:
                    student_data[local_key] = local_path
                else:
                    errors.append(f"Row {i} ({roll}): Could not download {photo_key}.")

        students.append(student_data)

    return {"students": students, "errors": errors, "total": len(students)}
