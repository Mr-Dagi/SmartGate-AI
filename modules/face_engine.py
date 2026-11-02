
from pathlib import Path
import logging

BASE_DIR = Path(__file__).resolve().parent.parent

DETECTOR_BACKEND = "opencv"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SmartGate.FaceEngine")


def detect_face(image_path):
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

        logger.info("Loading DeepFace")

        from deepface import DeepFace

        logger.info("Detecting faces")

        faces = DeepFace.extract_faces(
            img_path=str(image_path),
            detector_backend=DETECTOR_BACKEND,
            enforce_detection=True,
            align=True
        )

        face_count = len(faces)

        logger.info("Detected faces: %s", face_count)

        if face_count == 1:
            logger.info("Exactly one face detected")
            return True

        logger.warning(
            "Expected one face, but detected %s",
            face_count
        )

        return False

    except Exception:
        logger.exception("Face detection failed")
        return False


if __name__ == "__main__":
    image = (
        BASE_DIR
        / "storage"
        / "student_faces"
        / "DEMO001.jpg"
    )

    result = detect_face(image)

    print(
        "Face detection successful!"
        if result
        else "Face detection failed or needs review."
    )
