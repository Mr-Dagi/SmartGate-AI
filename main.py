
from pathlib import Path

from database.db import (
    initialize_database,
    get_student_by_card,
    log_verification
)

from modules.nfc_simulator import scan_card
from modules.face_verification import verify_face
from camera.live_capture import capture_live_face


BASE_DIR = Path(__file__).resolve().parent


def run_smartgate():

    initialize_database()

    print("\n========== SMARTGATE AI ==========")

    card_uid = scan_card()

    if not card_uid:
        print("No card scanned.")
        return

    student = get_student_by_card(card_uid)

    if not student:
        print("\nUNKNOWN CARD")
        print("Please contact the campus security desk.")
        return

    student_id = student["student_id"]

    print("\n========== STUDENT RECORD ==========")
    print("Student ID:", student_id)
    print("Name:", student["full_name"])
    print("Department:", student["department"])
    print("Status: Active")

    print("\n========== LIVE FACE CAPTURE ==========")

    captured = capture_live_face()

    if not captured:
        print("Face capture unsuccessful.")
        log_verification(
            student_id,
            card_uid,
            "REVIEW",
            "Live face capture unsuccessful"
        )
        return

    print("\n========== FACE VERIFICATION ==========")

    live_image = (
        BASE_DIR / "storage" / "student_faces" / "live"
        / "current_capture.jpg"
    )

    result = verify_face(student_id, live_image)

    log_verification(
        student_id,
        card_uid,
        result,
        "Automated face comparison result"
    )

    print("\n========== VERIFICATION RESULT ==========")

    if result == "MATCH":
        print("Face comparison: MATCH")
        print("Please proceed to the guard's normal check.")

    elif result == "MISMATCH":
        print("Face comparison: MISMATCH")
        print("Manual guard review required.")

    else:
        print("Face comparison: REVIEW")
        print("Manual guard review required.")

    print("\nVerification event recorded.")


if __name__ == "__main__":
    run_smartgate()
