
import cv2
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

LIVE_DIR = BASE_DIR / "storage" / "student_faces" / "live"
LIVE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_PATH = LIVE_DIR / "current_capture.jpg"

FACE_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades
    + "haarcascade_frontalface_default.xml"
)

REQUIRED_STABLE_FRAMES = 10
BLUR_THRESHOLD = 80.0
CAPTURE_TIMEOUT = 30
MIN_FACE_SIZE = 120
FACE_PADDING = 0.25


def calculate_sharpness(image):
    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    return cv2.Laplacian(
        gray,
        cv2.CV_64F
    ).var()


def crop_face(frame, face):
    x, y, width, height = face

    padding_x = int(width * FACE_PADDING)
    padding_y = int(height * FACE_PADDING)

    x1 = max(0, x - padding_x)
    y1 = max(0, y - padding_y)

    x2 = min(
        frame.shape[1],
        x + width + padding_x
    )

    y2 = min(
        frame.shape[0],
        y + height + padding_y
    )

    return frame[y1:y2, x1:x2].copy()


def capture_live_face():
    print("Starting SmartGate face capture...")

    if FACE_CASCADE.empty():
        print("ERROR: Face detection model could not be loaded.")
        return False

    camera = cv2.VideoCapture(
        0,
        cv2.CAP_DSHOW
    )

    if not camera.isOpened():
        print("ERROR: Camera could not be opened.")
        return False

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    stable_frames = 0
    start_time = time.monotonic()

    window_name = "SmartGate Face Capture"

    cv2.namedWindow(
        window_name,
        cv2.WINDOW_NORMAL
    )

    try:
        while (
            time.monotonic() - start_time
            < CAPTURE_TIMEOUT
        ):
            success, frame = camera.read()

            if not success or frame is None:
                print("ERROR: Failed to read camera frame.")
                return False

            gray = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2GRAY
            )

            faces = FACE_CASCADE.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(MIN_FACE_SIZE, MIN_FACE_SIZE)
            )

            display_frame = frame.copy()

            if len(faces) == 1:
                face = faces[0]

                face_crop = crop_face(
                    frame,
                    face
                )

                sharpness = calculate_sharpness(
                    face_crop
                )

                x, y, width, height = face

                if sharpness >= BLUR_THRESHOLD:
                    stable_frames += 1

                    color = (0, 255, 0)

                    message = (
                        f"Clear face - hold still "
                        f"({stable_frames}/{REQUIRED_STABLE_FRAMES})"
                    )

                else:
                    stable_frames = 0

                    color = (0, 165, 255)

                    message = "Image blurry - hold still"

                cv2.rectangle(
                    display_frame,
                    (x, y),
                    (x + width, y + height),
                    color,
                    2
                )

                cv2.putText(
                    display_frame,
                    message,
                    (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2
                )

                if stable_frames >= REQUIRED_STABLE_FRAMES:
                    saved = cv2.imwrite(
                        str(IMAGE_PATH),
                        face_crop,
                        [
                            cv2.IMWRITE_JPEG_QUALITY,
                            95
                        ]
                    )

                    if saved:
                        print("Face captured successfully!")
                        print(f"Sharpness: {sharpness:.2f}")
                        print(f"Saved: {IMAGE_PATH}")
                        return True

                    print("ERROR: Could not save face image.")
                    return False

            else:
                stable_frames = 0

                message = (
                    "No face detected"
                    if len(faces) == 0
                    else "Only one person should be visible"
                )

                cv2.putText(
                    display_frame,
                    message,
                    (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2
                )

            cv2.imshow(
                window_name,
                display_frame
            )

            if cv2.waitKey(10) & 0xFF == ord("q"):
                print("Capture cancelled.")
                return False

        print("Capture timed out. No suitable face image was saved.")
        return False

    except Exception as error:
        print(f"Camera error: {error}")
        return False

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    capture_live_face()
