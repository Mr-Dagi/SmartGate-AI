
import os
import sqlite3
import hashlib
import logging
import re

from pathlib import Path
from contextlib import contextmanager


BASE_DIR = Path(__file__).resolve().parent.parent

DB_DIR = Path(
    os.getenv("LOCALAPPDATA")
    or os.getenv("APPDATA")
    or str(Path.home())
) / "SmartGateAI"

DB_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DB_DIR / "smartgate.db"

SYSTEM_HEADER = "UNIQUE ID"
DEFAULT_UNIVERSITY = "Unity University"

DEMO_STUDENT = {
    "student_id": "STU000001",
    "full_name": "Ababa Belaw",
    "department": "Computer Science",
    "year_level": 4,
    "university": DEFAULT_UNIVERSITY
}

VALID_RESULTS = {
    "MATCH",
    "MISMATCH",
    "REVIEW",
    "PENDING"
}

STUDENT_ID_PREFIX = "STU"
STUDENT_ID_DIGITS = 6

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SmartGate.Database")


@contextmanager
def get_connection():
    connection = None

    try:
        connection = sqlite3.connect(
            str(DB_PATH),
            timeout=30
        )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")

        yield connection

        connection.commit()

    except Exception:
        if connection is not None and connection.in_transaction:
            try:
                connection.rollback()
            except sqlite3.Error:
                logger.exception("Database rollback failed.")

        raise

    finally:
        if connection is not None:
            connection.close()


def normalize_student_id(student_id):
    if not isinstance(student_id, str):
        raise ValueError("Student ID must be a string.")

    student_id = student_id.strip()

    if not student_id:
        raise ValueError("Student ID cannot be empty.")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", student_id):
        raise ValueError("Student ID contains invalid characters.")

    return student_id.upper()


def hash_card_uid(card_uid):
    if not isinstance(card_uid, str):
        raise ValueError("Card UID must be a string.")

    card_uid = card_uid.strip().upper()

    if not card_uid:
        raise ValueError("Card UID cannot be empty.")

    return hashlib.sha256(
        card_uid.encode("utf-8")
    ).hexdigest()


def _resolve_student_id(connection, student_id):
    if student_id is None:
        return None

    normalized_id = normalize_student_id(student_id)

    row = connection.execute("""
        SELECT student_id
        FROM students
        WHERE student_id = ? COLLATE NOCASE
    """, (normalized_id,)).fetchone()

    return row["student_id"] if row else None


def _generate_nfc_id(connection):
    row = connection.execute("""
        SELECT COUNT(*) AS total
        FROM cards
    """).fetchone()

    next_number = row["total"] + 1

    while True:
        nfc_id = f"NFC{next_number:06d}"

        exists = connection.execute("""
            SELECT 1
            FROM cards
            WHERE nfc_id = ?
        """, (nfc_id,)).fetchone()

        if not exists:
            return nfc_id

        next_number += 1


def generate_student_id():
    try:
        with get_connection() as connection:
            rows = connection.execute("""
                SELECT student_id
                FROM students
                WHERE student_id LIKE ?
            """, (f"{STUDENT_ID_PREFIX}%",)).fetchall()

            highest_number = 0

            for row in rows:
                match = re.fullmatch(
                    rf"{STUDENT_ID_PREFIX}(\d+)",
                    row["student_id"],
                    re.IGNORECASE
                )

                if match:
                    highest_number = max(
                        highest_number,
                        int(match.group(1))
                    )

            next_number = highest_number + 1

            while True:
                student_id = (
                    f"{STUDENT_ID_PREFIX}"
                    f"{next_number:0{STUDENT_ID_DIGITS}d}"
                )

                exists = connection.execute("""
                    SELECT 1
                    FROM students
                    WHERE student_id = ? COLLATE NOCASE
                """, (student_id,)).fetchone()

                if not exists:
                    return student_id

                next_number += 1

    except sqlite3.Error:
        logger.exception("Student ID generation failed.")
        return None


def initialize_database():
    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")

            connection.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    student_id TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    department TEXT NOT NULL,
                    year_level INTEGER NOT NULL,
                    enrollment_status TEXT DEFAULT 'active',
                    university TEXT NOT NULL DEFAULT 'Unity University'
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS cards (
                    card_uid_hash TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL UNIQUE,
                    nfc_id TEXT,
                    FOREIGN KEY (student_id)
                    REFERENCES students(student_id)
                )
            """)

            connection.execute("""
                CREATE TABLE IF NOT EXISTS verification_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT,
                    card_uid_hash TEXT,
                    verification_result TEXT NOT NULL,
                    reason TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (student_id)
                    REFERENCES students(student_id)
                )
            """)

            student_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(students)"
                ).fetchall()
            }

            if "university" not in student_columns:
                connection.execute("""
                    ALTER TABLE students
                    ADD COLUMN university TEXT NOT NULL
                    DEFAULT 'Unity University'
                """)

            card_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(cards)"
                ).fetchall()
            }

            if "nfc_id" not in card_columns:
                connection.execute("""
                    ALTER TABLE cards
                    ADD COLUMN nfc_id TEXT
                """)

            connection.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_students_student_id_nocase
                ON students(student_id COLLATE NOCASE)
            """)

            connection.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_cards_nfc_id
                ON cards(nfc_id)
                WHERE nfc_id IS NOT NULL
            """)

            existing_cards = connection.execute("""
                SELECT card_uid_hash
                FROM cards
                WHERE nfc_id IS NULL
            """).fetchall()

            for card in existing_cards:
                nfc_id = _generate_nfc_id(connection)

                connection.execute("""
                    UPDATE cards
                    SET nfc_id = ?
                    WHERE card_uid_hash = ?
                """, (
                    nfc_id,
                    card["card_uid_hash"]
                ))

            demo_exists = connection.execute("""
                SELECT 1
                FROM students
                WHERE student_id = ?
            """, (DEMO_STUDENT["student_id"],)).fetchone()

            if not demo_exists:
                connection.execute("""
                    INSERT INTO students (
                        student_id,
                        full_name,
                        department,
                        year_level,
                        university,
                        enrollment_status
                    )
                    VALUES (?, ?, ?, ?, ?, 'active')
                """, (
                    DEMO_STUDENT["student_id"],
                    DEMO_STUDENT["full_name"],
                    DEMO_STUDENT["department"],
                    DEMO_STUDENT["year_level"],
                    DEMO_STUDENT["university"]
                ))

                logger.info(
                    "Demo student %s created.",
                    DEMO_STUDENT["student_id"]
                )

        logger.info(
            "%s database initialized successfully.",
            SYSTEM_HEADER
        )

        return True

    except sqlite3.Error:
        logger.exception(
            "Database initialization failed: %s",
            DB_PATH
        )
        return False


def register_student(
    student_id,
    full_name,
    department,
    year_level,
    card_uid=None,
    university=DEFAULT_UNIVERSITY
):
    try:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                student_id,
                full_name,
                department,
                university
            )
        ):
            return False

        student_id = normalize_student_id(student_id)
        full_name = full_name.strip()
        department = department.strip()
        university = university.strip()

        if (
            isinstance(year_level, bool)
            or not isinstance(year_level, int)
            or year_level < 1
        ):
            return False

        card_hash = (
            hash_card_uid(card_uid)
            if card_uid
            else None
        )

        with get_connection() as connection:
            connection.execute("""
                INSERT INTO students (
                    student_id,
                    full_name,
                    department,
                    year_level,
                    university
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                student_id,
                full_name,
                department,
                year_level,
                university
            ))

            if card_hash:
                nfc_id = _generate_nfc_id(connection)

                connection.execute("""
                    INSERT INTO cards (
                        card_uid_hash,
                        student_id,
                        nfc_id
                    )
                    VALUES (?, ?, ?)
                """, (
                    card_hash,
                    student_id,
                    nfc_id
                ))

        logger.info("Student %s registered.", student_id)
        return True

    except sqlite3.IntegrityError:
        logger.warning("Student ID or NFC card already exists.")
        return False

    except (sqlite3.Error, ValueError):
        logger.exception("Student registration failed.")
        return False


def create_student(
    full_name,
    department,
    year_level,
    card_uid=None,
    university=DEFAULT_UNIVERSITY
):
    student_id = generate_student_id()

    if not student_id:
        return None

    success = register_student(
        student_id,
        full_name,
        department,
        year_level,
        card_uid,
        university
    )

    return student_id if success else None


def assign_card(student_id, card_uid):
    try:
        student_id = normalize_student_id(student_id)
        card_hash = hash_card_uid(card_uid)

        with get_connection() as connection:
            actual_student_id = _resolve_student_id(
                connection,
                student_id
            )

            if not actual_student_id:
                return False

            existing_card = connection.execute("""
                SELECT student_id
                FROM cards
                WHERE card_uid_hash = ?
            """, (card_hash,)).fetchone()

            if existing_card:
                return False

            existing_assignment = connection.execute("""
                SELECT card_uid_hash
                FROM cards
                WHERE student_id = ? COLLATE NOCASE
            """, (actual_student_id,)).fetchone()

            if existing_assignment:
                return False

            nfc_id = _generate_nfc_id(connection)

            connection.execute("""
                INSERT INTO cards (
                    card_uid_hash,
                    student_id,
                    nfc_id
                )
                VALUES (?, ?, ?)
            """, (
                card_hash,
                actual_student_id,
                nfc_id
            ))

        logger.info("NFC card assigned to %s.", student_id)
        return nfc_id

    except (sqlite3.Error, ValueError):
        logger.exception("NFC card assignment failed.")
        return False


def remove_card(student_id):
    try:
        student_id = normalize_student_id(student_id)

        with get_connection() as connection:
            actual_student_id = _resolve_student_id(
                connection,
                student_id
            )

            if not actual_student_id:
                return False

            cursor = connection.execute("""
                DELETE FROM cards
                WHERE student_id = ?
            """, (actual_student_id,))

            return cursor.rowcount > 0

    except (sqlite3.Error, ValueError):
        logger.exception("NFC card removal failed.")
        return False


def get_student_by_id(student_id):
    try:
        student_id = normalize_student_id(student_id)

        with get_connection() as connection:
            return connection.execute("""
                SELECT
                    students.*,
                    cards.nfc_id
                FROM students
                LEFT JOIN cards
                    ON students.student_id = cards.student_id
                WHERE students.student_id = ? COLLATE NOCASE
            """, (student_id,)).fetchone()

    except (sqlite3.Error, ValueError):
        logger.exception("Student lookup failed.")
        return None


def get_student_by_card(card_uid):
    try:
        card_hash = hash_card_uid(card_uid)

        with get_connection() as connection:
            return connection.execute("""
                SELECT
                    students.*,
                    cards.nfc_id
                FROM students
                JOIN cards
                    ON students.student_id = cards.student_id
                WHERE cards.card_uid_hash = ?
            """, (card_hash,)).fetchone()

    except (sqlite3.Error, ValueError):
        logger.exception("Card lookup failed.")
        return None


def get_card_by_student(student_id):
    try:
        student_id = normalize_student_id(student_id)

        with get_connection() as connection:
            return connection.execute("""
                SELECT
                    nfc_id,
                    student_id
                FROM cards
                WHERE student_id = ? COLLATE NOCASE
            """, (student_id,)).fetchone()

    except (sqlite3.Error, ValueError):
        logger.exception("Student card lookup failed.")
        return None


def log_verification(
    student_id,
    card_uid,
    result,
    reason
):
    if result not in VALID_RESULTS:
        raise ValueError("Invalid verification result.")

    if student_id is not None:
        if not isinstance(student_id, str) or not student_id.strip():
            raise ValueError("Invalid student ID.")

    with get_connection() as connection:
        actual_student_id = (
            _resolve_student_id(connection, student_id)
            if student_id is not None
            else None
        )

        if student_id is not None and actual_student_id is None:
            raise ValueError("Student does not exist.")

        card_hash = (
            hash_card_uid(card_uid)
            if card_uid
            else None
        )

        connection.execute("""
            INSERT INTO verification_events (
                student_id,
                card_uid_hash,
                verification_result,
                reason
            )
            VALUES (?, ?, ?, ?)
        """, (
            actual_student_id,
            card_hash,
            result,
            reason
        ))


def get_dashboard_stats():
    with get_connection() as connection:
        students = connection.execute("""
            SELECT COUNT(*)
            FROM students
        """).fetchone()[0]

        results = connection.execute("""
            SELECT
                verification_result,
                COUNT(*) AS total
            FROM verification_events
            GROUP BY verification_result
        """).fetchall()

        counts = {
            row["verification_result"]: row["total"]
            for row in results
        }

        total = sum(counts.values())

        return {
            "students": students,
            "total_verifications": total,
            "matches": counts.get("MATCH", 0),
            "mismatches": counts.get("MISMATCH", 0),
            "reviews": counts.get("REVIEW", 0),
            "pending": counts.get("PENDING", 0)
        }


def get_recent_activity(limit=10):
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
    ):
        limit = 10

    with get_connection() as connection:
        return connection.execute("""
            SELECT
                verification_events.event_id,
                verification_events.student_id,
                students.full_name,
                verification_events.verification_result,
                verification_events.reason,
                verification_events.timestamp
            FROM verification_events
            LEFT JOIN students
                ON verification_events.student_id =
                   students.student_id
            ORDER BY verification_events.event_id DESC
            LIMIT ?
        """, (limit,)).fetchall()


def get_all_students():
    with get_connection() as connection:
        return connection.execute("""
            SELECT
                students.student_id,
                students.full_name,
                students.department,
                students.year_level,
                students.enrollment_status,
                students.university,
                cards.nfc_id
            FROM students
            LEFT JOIN cards
                ON students.student_id = cards.student_id
            ORDER BY students.full_name
        """).fetchall()


def search_students(search_term):
    if search_term is None:
        search_term = ""

    term = f"%{str(search_term).strip()}%"

    with get_connection() as connection:
        return connection.execute("""
            SELECT
                students.student_id,
                students.full_name,
                students.department,
                students.year_level,
                students.enrollment_status,
                students.university,
                cards.nfc_id
            FROM students
            LEFT JOIN cards
                ON students.student_id = cards.student_id
            WHERE students.student_id LIKE ? COLLATE NOCASE
               OR students.full_name LIKE ? COLLATE NOCASE
               OR students.department LIKE ? COLLATE NOCASE
               OR students.university LIKE ? COLLATE NOCASE
            ORDER BY students.full_name
        """, (
            term,
            term,
            term,
            term
        )).fetchall()


if __name__ == "__main__":
    if initialize_database():
        print("System:", SYSTEM_HEADER)
        print("University:", DEFAULT_UNIVERSITY)
        print("Database location:", DB_PATH)
        print("Dashboard statistics:", get_dashboard_stats())
        print("Demo student:", dict(get_student_by_id("STU000001")))
        print("Next available Student ID:", generate_student_id())
