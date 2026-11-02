
import cv2
from pathlib import Path

SAVE_DIR = Path(__file__).resolve().parent.parent / "storage" / "student_faces"
SAVE_DIR.mkdir(parents=True, exist_ok=True)


def capture_face(student_id):
    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        print("Cannot access webcam.")
        return None

    print("Camera ready. Press SPACE to capture or Q to cancel.")

    captured_image = None

    while True:
        success, frame = camera.read()

        if not success:
            break

        cv2.imshow("SmartGate Face Enrollment", frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord(" "):
            captured_image = SAVE_DIR / f"{student_id}.jpg"
            cv2.imwrite(str(captured_image), frame)
            print("Demo image captured!")
            break

        if key == ord("q"):
            break

    camera.release()
    cv2.destroyAllWindows()

    return str(captured_image) if captured_image else None


if __name__ == "__main__":
    capture_face("DEMO001")
