
from pathlib import Path
import logging
import re

BASE_DIR = Path(__file__).resolve().parent.parent

REFERENCE_DIR = BASE_DIR / "storage" / "student_faces" / "reference"
LIVE_DIR = BASE_DIR / "storage" / "student_faces" / "live"

MODEL_NAME = "Facenet512"
DETECTOR_BACKEND = "opencv"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SmartGate.FaceVerification")


def validate_image(image_path, deepface):
    try:
        if not image_path.is_file():
            logger.warning("Image file does not exist: %s", image_path)
            return False

        faces = deepface.extract_faces(
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

        return True

    except Exception:
        logger.exception("Image validation failed")
        return False


def verify_face(student_id, live_image_path):
    logger.info("Starting face verification")

    if not student_id or not isinstance(student_id, str):
        logger.warning("Invalid student ID")
        return "REVIEW"

    if not re.fullmatch(r"[A-Za-z0-9_-]+", student_id):
        logger.warning("Student ID contains invalid characters")
        return "REVIEW"

    reference_path = (
        REFERENCE_DIR / f"{student_id}.jpg"
    ).resolve()

    try:
        live_image_path = Path(live_image_path)

        if not live_image_path.is_absolute():
            live_image_path = BASE_DIR / live_image_path

        live_image_path = live_image_path.resolve()

        reference_path.relative_to(REFERENCE_DIR.resolve())
        live_image_path.relative_to(LIVE_DIR.resolve())

    except (ValueError, TypeError, OSError):
        logger.warning("Invalid image path")
        return "REVIEW"

    if not reference_path.is_file():
        logger.warning(
            "Reference image not found for student %s",
            student_id
        )
        return "REVIEW"

    if not live_image_path.is_file():
        logger.warning("Live image not found")
        return "REVIEW"

    try:
        logger.info("Loading DeepFace")
        from deepface import DeepFace

        logger.info("Validating reference image")
        if not validate_image(reference_path, DeepFace):
            return "REVIEW"

        logger.info("Validating live image")
        if not validate_image(live_image_path, DeepFace):
            return "REVIEW"

        logger.info("Comparing face embeddings")

        result = DeepFace.verify(
            img1_path=str(reference_path),
            img2_path=str(live_image_path),
            model_name=MODEL_NAME,
            detector_backend=DETECTOR_BACKEND,
            enforce_detection=True,
            align=True
        )

        verified = result.get("verified")

        if not isinstance(verified, bool):
            logger.warning("Unexpected DeepFace response")
            return "REVIEW"

        if verified:
            logger.info("Verification result: MATCH")
            return "MATCH"

        logger.info("Verification result: MISMATCH")
        return "MISMATCH"

    except Exception:
        logger.exception(
            "Face verification failed for student %s",
            student_id
        )
        return "REVIEW"


if __name__ == "__main__":
    result = verify_face(
        "TEST002",
        LIVE_DIR / "current_capture.jpg"
    )

    print(f"Verification result: {result}")
