
def scan_card():
    print("\n========== SMARTGATE NFC SCANNER ==========")

    card_uid = input("Scan or enter student card UID: ").strip()

    if not card_uid:
        print("No card detected!")
        return None

    print("Card scanned successfully!")
    return card_uid
