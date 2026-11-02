from pathlib import Path
from deepface import DeepFace

BASE_DIR = Path(__file__).resolve().parent.parent
REFERENCE_DIR = BASE_DIR / "storage" / "student_faces" / "reference"
REFERENCE_DIR.mkdir(parents=True, exist_ok=True)


def enroll_face(student_id, image_path):
    image_path = Path(image_path)
    reference_path = REFERENCE_DIR / f"{student_id}.jpg"

    if not image_path.exists():
        print("Image not found!")
        return False

    if reference_path.exists():
        print("Reference image already exists!")
        return False

    try:
        faces = DeepFace.extract_faces(
            img_path=str(image_path),
            detector_backend="opencv",
            enforce_detection=True
        )

        if len(faces) != 1:
            print("Enrollment requires exactly one detected face.")
            return False

        import shutil
        shutil.copy2(image_path, reference_path)

        print("Face enrolled successfully!")
        return True

    except Exception as error:
        print("Enrollment failed:", error)
        return False