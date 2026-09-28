"""
app/services/face_service.py
-----------------------------
All face-recognition logic lives here so routes stay thin.

Public API
----------
encode_face(image_path)                           -> np.ndarray | None
save_student_encoding(student_id, roll, paths)    -> str (path to .npy)
load_all_encodings(department, semester)          -> dict
recognize_faces_in_image(image_path, encodings)   -> list[dict]
draw_boxes_on_image(image_path, results)          -> str (annotated path)
"""

import os
import logging
import json
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Try to import face_recognition; degrade gracefully so the rest of the app
# still loads even if dlib is not compiled on this machine.
try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    logger.warning(
        "face_recognition library not found. "
        "Install it with: pip install face-recognition\n"
        "Face recognition features will be DISABLED."
    )

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("opencv-python not found. Annotated images will not be generated.")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_image_rgb(image_path: str) -> Optional[np.ndarray]:
    """Load an image file and return it as an RGB numpy array."""
    path = Path(image_path)
    if not path.exists():
        logger.error("Image not found: %s", image_path)
        return None
    try:
        if FACE_RECOGNITION_AVAILABLE:
            img = face_recognition.load_image_file(str(path))
            return img  # already RGB
        elif CV2_AVAILABLE:
            img = cv2.imread(str(path))
            return cv2.cvtColor(img, cv2.COLOR_BGR2RGB) if img is not None else None
        elif PIL_AVAILABLE:
            return np.array(Image.open(str(path)).convert("RGB"))
    except Exception as exc:
        logger.error("Failed to load image %s: %s", image_path, exc)
    return None


# ---------------------------------------------------------------------------
# Core face-service functions
# ---------------------------------------------------------------------------

def encode_face(image_path: str) -> Optional[np.ndarray]:
    """
    Detect the *first* face in the image and return its 128-d encoding.

    Returns None if face_recognition is unavailable, no face is found,
    or the image cannot be loaded.
    """
    if not FACE_RECOGNITION_AVAILABLE:
        logger.warning("face_recognition not available; skipping encode_face.")
        return None

    img = _load_image_rgb(image_path)
    if img is None:
        return None

    try:
        locations = face_recognition.face_locations(img, model="hog")
        if not locations:
            logger.warning("No face detected in %s", image_path)
            return None
        # Use only the first (largest) face
        encodings = face_recognition.face_encodings(img, known_face_locations=[locations[0]])
        return encodings[0] if encodings else None
    except Exception as exc:
        logger.error("encode_face error on %s: %s", image_path, exc)
        return None


def save_student_encoding(
    student_id: int,
    roll_number: str,
    image_paths: list,
    face_data_folder: str,
) -> Optional[str]:
    """
    Encode up to 3 photos for a student, average the encodings, and save
    the result as ``<face_data_folder>/<roll_number>.npy``.

    Also writes a ``<roll_number>.json`` sidecar with metadata.

    Returns the path to the saved .npy file, or None on failure.
    """
    if not FACE_RECOGNITION_AVAILABLE:
        logger.warning("face_recognition not available; cannot save encoding.")
        return None

    encodings = []
    for path in image_paths:
        if not path:
            continue
        enc = encode_face(path)
        if enc is not None:
            encodings.append(enc)

    if not encodings:
        logger.warning(
            "No valid face encodings produced for student %s (%s)",
            student_id, roll_number,
        )
        return None

    avg_encoding = np.mean(encodings, axis=0)

    os.makedirs(face_data_folder, exist_ok=True)
    npy_path = os.path.join(face_data_folder, f"{roll_number}.npy")
    np.save(npy_path, avg_encoding)

    # Write sidecar JSON for quick metadata lookup
    meta = {"student_id": student_id, "roll_number": roll_number, "num_photos": len(encodings)}
    json_path = os.path.join(face_data_folder, f"{roll_number}.json")
    with open(json_path, "w") as f:
        json.dump(meta, f)

    logger.info(
        "Saved encoding for %s (%d photo(s) averaged) -> %s",
        roll_number, len(encodings), npy_path,
    )
    return npy_path


def load_all_encodings(
    face_data_folder: str,
    department: Optional[str] = None,
    semester: Optional[str] = None,
) -> dict:
    """
    Load all .npy encoding files from *face_data_folder*.

    Optionally filter by department / semester if the sidecar JSON
    contains those fields (requires the sync flow to write them).

    Returns
    -------
    dict
        ``{ roll_number: { 'encoding': np.ndarray,
                           'student_id': int,
                           'name': str } }``
    """
    known: dict = {}
    folder = Path(face_data_folder)
    if not folder.exists():
        return known

    # Lazy import to avoid circular imports
    try:
        from app.models import Student
        from app import db
        students_by_roll = {
            s.roll_number: s
            for s in Student.query.filter_by(is_active=True).all()
        }
    except Exception:
        students_by_roll = {}

    for npy_file in folder.glob("*.npy"):
        roll = npy_file.stem
        try:
            encoding = np.load(str(npy_file))
        except Exception as exc:
            logger.warning("Could not load encoding %s: %s", npy_file, exc)
            continue

        student = students_by_roll.get(roll)
        if student is None:
            # Still include it but with minimal info
            known[roll] = {"encoding": encoding, "student_id": None, "name": roll}
        else:
            known[roll] = {
                "encoding": encoding,
                "student_id": student.id,
                "name": student.full_name,
            }

    logger.debug("Loaded %d face encodings from %s", len(known), face_data_folder)
    return known


def recognize_faces_in_image(
    classroom_image_path: str,
    known_encodings: dict,
    tolerance: float = 0.5,
) -> list:
    """
    Detect all faces in the classroom photo and match them to known students.

    Parameters
    ----------
    classroom_image_path : str
        Absolute path to the classroom photograph.
    known_encodings : dict
        Output of :func:`load_all_encodings`.
    tolerance : float
        Face-distance threshold (lower = stricter). Default 0.5.

    Returns
    -------
    list[dict]
        One entry per detected face::

            {
                'location':    (top, right, bottom, left),
                'roll_number': str | None,
                'student_id':  int | None,
                'name':        str | None,
                'confidence':  float,   # 0.0 – 1.0
                'status':      'recognized' | 'unknown',
            }
    """
    results = []

    if not FACE_RECOGNITION_AVAILABLE:
        logger.warning("face_recognition not available; returning empty results.")
        return results

    img = _load_image_rgb(classroom_image_path)
    if img is None:
        return results

    try:
        # Detect face locations (CNN is more accurate but slower; use hog for speed)
        locations = face_recognition.face_locations(img, model="hog")
        if not locations:
            logger.info("No faces detected in classroom photo.")
            return results

        # Encode every detected face
        unknown_encodings = face_recognition.face_encodings(img, known_face_locations=locations)
    except Exception as exc:
        logger.error("Face detection/encoding failed: %s", exc)
        return results

    # Build parallel lists for bulk comparison
    known_rolls = list(known_encodings.keys())
    known_enc_list = [known_encodings[r]["encoding"] for r in known_rolls]

    for location, unknown_enc in zip(locations, unknown_encodings):
        if known_enc_list:
            # face_recognition.face_distance returns lower values for closer matches
            distances = face_recognition.face_distance(known_enc_list, unknown_enc)
            best_idx = int(np.argmin(distances))
            best_dist = float(distances[best_idx])
            confidence = max(0.0, round(1.0 - best_dist, 3))

            if best_dist <= tolerance:
                roll = known_rolls[best_idx]
                info = known_encodings[roll]
                results.append({
                    "location":    location,
                    "roll_number": roll,
                    "student_id":  info["student_id"],
                    "name":        info["name"],
                    "confidence":  confidence,
                    "status":      "recognized",
                })
            else:
                results.append({
                    "location":    location,
                    "roll_number": None,
                    "student_id":  None,
                    "name":        None,
                    "confidence":  confidence,
                    "status":      "unknown",
                })
        else:
            results.append({
                "location":    location,
                "roll_number": None,
                "student_id":  None,
                "name":        None,
                "confidence":  0.0,
                "status":      "unknown",
            })

    logger.info(
        "Recognized %d / %d faces in classroom photo.",
        sum(1 for r in results if r["status"] == "recognized"),
        len(results),
    )
    return results


def draw_boxes_on_image(
    image_path: str,
    recognition_results: list,
    output_folder: str,
) -> Optional[str]:
    """
    Draw coloured bounding boxes on the classroom photo.
    - Green  : recognized student
    - Red    : unknown face

    The annotated image is saved in *output_folder* with an ``_annotated``
    suffix and the same file extension.

    Returns the path to the saved image, or None on failure.
    """
    if not CV2_AVAILABLE:
        logger.warning("OpenCV not available; cannot draw annotation boxes.")
        return None

    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        logger.error("cv2.imread failed for %s", image_path)
        return None

    GREEN = (0, 200, 80)
    RED   = (0, 60, 220)
    FONT  = cv2.FONT_HERSHEY_SIMPLEX

    for face in recognition_results:
        top, right, bottom, left = face["location"]
        color = GREEN if face["status"] == "recognized" else RED
        thickness = 2

        cv2.rectangle(img_bgr, (left, top), (right, bottom), color, thickness)

        label = face.get("name") or "Unknown"
        conf  = face.get("confidence", 0.0)
        text  = f"{label} ({conf:.0%})" if face["status"] == "recognized" else "Unknown"

        # Background rectangle for text
        (tw, th), _ = cv2.getTextSize(text, FONT, 0.5, 1)
        cv2.rectangle(img_bgr, (left, bottom - th - 6), (left + tw + 4, bottom), color, -1)
        cv2.putText(img_bgr, text, (left + 2, bottom - 4), FONT, 0.5, (255, 255, 255), 1)

    os.makedirs(output_folder, exist_ok=True)
    src = Path(image_path)
    out_name = src.stem + "_annotated" + src.suffix
    out_path = os.path.join(output_folder, out_name)
    cv2.imwrite(out_path, img_bgr)

    logger.info("Annotated image saved -> %s", out_path)
    return out_path


def get_face_thumbnail(image_path: str, location: tuple, output_folder: str, prefix: str = "thumb") -> Optional[str]:
    """
    Crop and save a face thumbnail from *image_path* at *location*.

    Parameters
    ----------
    location : tuple
        (top, right, bottom, left) as returned by face_recognition.

    Returns the path to the saved thumbnail, or None.
    """
    if not CV2_AVAILABLE:
        return None

    img = cv2.imread(image_path)
    if img is None:
        return None

    top, right, bottom, left = location
    # Add small padding
    pad = 10
    h, w = img.shape[:2]
    top    = max(0, top - pad)
    left   = max(0, left - pad)
    bottom = min(h, bottom + pad)
    right  = min(w, right + pad)

    crop = img[top:bottom, left:right]
    os.makedirs(output_folder, exist_ok=True)
    import uuid
    out_path = os.path.join(output_folder, f"{prefix}_{uuid.uuid4().hex[:8]}.jpg")
    cv2.imwrite(out_path, crop)
    return out_path
