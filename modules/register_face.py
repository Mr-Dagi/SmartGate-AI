
from pathlib import Path
import logging
import re

import cv2

BASE_DIR = Path(__file__).resolve().parent.parent

REFERENCE_DIR = (
    BASE_DIR / "storage" / "student_faces" / "reference"
)

REFERENCE_DIR.mkdir(
    parents=True,
    exist_ok=True
)

DETECTOR_BACKEND = "opencv"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SmartGate.FaceRegistration")


def register_face(student_id, image_path):
    if not isinstance(student_id, str) or not student_id.strip():
        logger.warning("Invalid student ID")
        return False

    student_id = student_id.strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]+", student_id):
        logger.warning("Student ID contains invalid characters")
        return False

    try:
        image_path = Path(image_path)

        if not image_path.is_absolute():
            image_path = BASE_DIR / image_path

        image_path = image_path.resolve()

        if not image_path.is_file():
            logger.warning("Image not found: %s", image_path)
            return False

        if image_path.suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp"
        }:
            logger.warning("Unsupported image format")
            return False

        image = cv2.imread(str(image_path))

        if image is None:
            logger.warning("Image could not be read")
            return False

        destination = (
            REFERENCE_DIR / f"{student_id}.jpg"
        )

        if destination.exists():
            logger.warning(
                "Reference image already exists for %s",
                student_id
            )
            return False

        logger.info("Loading DeepFace")

        from deepface import DeepFace

        logger.info("Checking reference image")

        faces = DeepFace.extract_faces(
            img_path=str(image_path),
            detector_backend=DETECTOR_BACKEND,
            enforce_detection=True,
            align=True
        )

        if len(faces) != 1:
            logger.warning(
                "Expected exactly one face, detected %s",
                len(faces)
            )
            return False

        temporary_destination = (
            REFERENCE_DIR / f"{student_id}.tmp.jpg"
        )

        saved = cv2.imwrite(
            str(temporary_destination),
            image,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                95
            ]
        )

        if not saved:
            logger.error("Could not save reference image")
            return False

        if not temporary_destination.replace(destination):
            logger.error("Could not finalize reference image")
            return False

        logger.info(
            "Reference face registered successfully: %s",
            destination
        )

        return True

    except Exception:
        logger.exception("Face registration failed")

        temporary_destination = (
            REFERENCE_DIR / f"{student_id}.tmp.jpg"
        )

        if temporary_destination.exists():
            temporary_destination.unlink()

        return False


if __name__ == "__main__":
    result = register_face(
        "TEST002",
        BASE_DIR
        / "storage"
        / "student_faces"
        / "DEMO001.jpg"
    )

    print(
        "Registration successful!"
        if result
        else "Registration failed."
    )
