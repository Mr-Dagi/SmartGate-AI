
import qrcode
from pathlib import Path
from urllib.parse import urlencode

BASE_URL = "http://192.168.18.24:8000/phone-scan"


def generate_student_qr(card_uid):
    output_dir = Path("storage/qr_codes")
    output_dir.mkdir(parents=True, exist_ok=True)

    params = urlencode({"card_uid": card_uid})
    verification_url = f"{BASE_URL}?{params}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4
    )

    qr.add_data(verification_url)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="#101827",
        back_color="white"
    )

    output_path = output_dir / "student_id.png"
    image.save(output_path)

    print("\nQR CODE GENERATED")
    print(f"Student credential: {card_uid}")
    print(f"Verification URL: {verification_url}")
    print(f"Saved to: {output_path}")

    return output_path


if __name__ == "__main__":
    card_uid = input("Enter student card UID: ").strip()

    if card_uid:
        generate_student_qr(card_uid)
    else:
        print("Card UID cannot be empty.")
