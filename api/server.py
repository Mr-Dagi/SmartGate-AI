
import logging
from pathlib import Path
from threading import Thread, Lock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from database.db import (
    initialize_database,
    get_student_by_card,
    log_verification
)

from camera.live_capture import capture_live_face
from modules.face_verification import verify_face
from api.services.ai_service import chat_with_ai


BASE_DIR = Path(__file__).resolve().parent.parent
LIVE_IMAGE = (
    BASE_DIR
    / "storage"
    / "student_faces"
    / "live"
    / "current_capture.jpg"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("SmartGateAI")

app = FastAPI(
    title="SmartGate AI API",
    description="Student verification and AI communication API",
    version="2.1.0"
)

initialize_database()

verification_lock = Lock()
jobs_lock = Lock()
verification_jobs = {}


class CardScan(BaseModel):
    card_uid: str = Field(min_length=1, max_length=256)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


def update_job(job_id, status, result=None, message=None):
    with jobs_lock:
        verification_jobs[job_id] = {
            "status": status,
            "result": result,
            "message": message
        }


def run_face_verification(job_id, student_id, card_uid):
    acquired = verification_lock.acquire(blocking=False)

    if not acquired:
        update_job(
            job_id,
            "completed",
            "REVIEW",
            "Another verification is already running."
        )
        return

    result = "REVIEW"
    reason = "Verification could not be completed."

    try:
        update_job(
            job_id,
            "processing",
            message="Starting automatic face capture."
        )

        if not capture_live_face():
            reason = "Automatic face capture unsuccessful."
        elif not LIVE_IMAGE.exists():
            reason = "Captured image was not found."
        else:
            result = verify_face(student_id, LIVE_IMAGE)

            if result == "MATCH":
                reason = "Face comparison returned MATCH."
            elif result == "MISMATCH":
                reason = "Face comparison returned MISMATCH."
            else:
                result = "REVIEW"
                reason = "Face comparison requires manual review."

        log_verification(
            student_id,
            card_uid,
            result,
            reason
        )

        update_job(
            job_id,
            "completed",
            result,
            reason
        )

        logger.info(
            "Verification completed: student=%s result=%s",
            student_id,
            result
        )

    except Exception:
        logger.exception("Verification failed for job %s", job_id)

        try:
            log_verification(
                student_id,
                card_uid,
                "REVIEW",
                "Unexpected verification error."
            )
        except Exception:
            logger.exception("Could not save verification event.")

        update_job(
            job_id,
            "completed",
            "REVIEW",
            "Unexpected error. Manual review required."
        )

    finally:
        verification_lock.release()


@app.get("/")
def home():
    return {
        "system": "SmartGate AI",
        "status": "online",
        "version": "2.1.0"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "camera_busy": verification_lock.locked()
    }


@app.post("/scan-card")
def scan_card(data: CardScan):
    card_uid = data.card_uid.strip()

    if not card_uid:
        return {
            "success": False,
            "message": "Card UID is required."
        }

    student = get_student_by_card(card_uid)

    if not student:
        return {
            "success": False,
            "message": "Unknown card."
        }

    return {
        "success": True,
        "message": "Student identified.",
        "student": {
            "student_id": student["student_id"],
            "full_name": student["full_name"],
            "department": student["department"],
            "year_level": student["year_level"]
        }
    }


@app.post("/start-verification")
def start_verification(data: CardScan):
    card_uid = data.card_uid.strip()

    if not card_uid:
        return {
            "success": False,
            "message": "Card UID is required."
        }

    student = get_student_by_card(card_uid)

    if not student:
        return {
            "success": False,
            "message": "Unknown card."
        }

    if verification_lock.locked():
        return {
            "success": False,
            "message": "Another verification is already running."
        }

    job_id = str(uuid4())

    update_job(
        job_id,
        "processing",
        message="Verification queued."
    )

    worker = Thread(
        target=run_face_verification,
        args=(job_id, student["student_id"], card_uid),
        daemon=True
    )

    worker.start()

    return {
        "success": True,
        "job_id": job_id,
        "student": {
            "student_id": student["student_id"],
            "full_name": student["full_name"]
        },
        "message": "Automatic face verification started."
    }


@app.get("/verification-status/{job_id}")
def verification_status(job_id: str):
    with jobs_lock:
        job = verification_jobs.get(job_id)

    if not job:
        return {
            "success": False,
            "message": "Verification job not found."
        }

    return {
        "success": True,
        "status": job["status"],
        "result": job["result"],
        "message": job["message"]
    }


@app.post("/chat")
def chatbot(request: ChatRequest):
    message = request.message.strip()

    if not message:
        return {
            "success": False,
            "reply": "Please enter a message."
        }

    history = [
        item for item in request.history[-10:]
        if isinstance(item, dict)
        and item.get("role") in ["user", "assistant"]
        and isinstance(item.get("content"), str)
    ]

    return chat_with_ai(message, history)


@app.get("/phone-scan", response_class=HTMLResponse)
def phone_scan():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>SmartGate AI</title>

        <style>
            * {
                box-sizing: border-box;
            }

            body {
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                padding: 20px;
                background: #080f1c;
                color: white;
                font-family: Arial, sans-serif;
            }

            .container {
                width: 100%;
                max-width: 420px;
                padding: 30px;
                background: #142033;
                border: 1px solid #26374e;
                border-radius: 20px;
                text-align: center;
            }

            h1 {
                color: #06b6d4;
            }

            p {
                color: #cbd5e1;
            }

            #result {
                margin-top: 22px;
                padding: 18px;
                border-radius: 12px;
                background: #0b1525;
                overflow-wrap: anywhere;
            }

            .hidden {
                display: none;
            }

            .status {
                color: #06b6d4;
                font-weight: bold;
            }
        </style>
    </head>

    <body>
        <main class="container">
            <h1>SMARTGATE AI</h1>
            <p>Student Identity Verification</p>

            <div id="student"></div>
            <div id="result" class="hidden"></div>
        </main>

        <script>
            const cardUid =
                new URLSearchParams(window.location.search).get("card_uid");

            const result = document.getElementById("result");
            const studentBox = document.getElementById("student");

            let jobId = null;
            let pollingTimer = null;

            function showMessage(message) {
                result.classList.remove("hidden");
                result.textContent = message;
            }

            async function startVerification() {
                if (!cardUid) {
                    showMessage("No QR credential received.");
                    return;
                }

                showMessage("Checking student credential...");

                try {
                    const response = await fetch("/start-verification", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            card_uid: cardUid
                        })
                    });

                    const data = await response.json();

                    if (!response.ok || !data.success) {
                        showMessage(
                            data.message || "Verification could not start."
                        );
                        return;
                    }

                    jobId = data.job_id;

                    studentBox.textContent =
                        "Student: " + data.student.full_name;

                    showMessage(
                        "Credential accepted. Automatic face capture started on the laptop."
                    );

                    checkStatus();

                } catch (error) {
                    showMessage(
                        "Could not connect to SmartGate AI."
                    );
                }
            }

            async function checkStatus() {
                if (!jobId) return;

                try {
                    const response = await fetch(
                        "/verification-status/" +
                        encodeURIComponent(jobId)
                    );

                    const data = await response.json();

                    if (!response.ok || !data.success) {
                        showMessage(
                            data.message || "Could not retrieve status."
                        );
                        return;
                    }

                    if (data.status === "processing") {
                        showMessage(
                            data.message ||
                            "Waiting for automatic face verification..."
                        );

                        pollingTimer = setTimeout(
                            checkStatus,
                            1500
                        );

                        return;
                    }

                    const messages = {
                        MATCH:
                            "MATCH: Face comparison passed. Continue with the normal human review process.",

                        MISMATCH:
                            "MISMATCH: Manual review required.",

                        REVIEW:
                            "REVIEW: Verification could not be completed. Manual review required."
                    };

                    showMessage(
                        messages[data.result] ||
                        "Manual review required."
                    );

                } catch (error) {
                    showMessage(
                        "Unable to retrieve verification result."
                    );

                    pollingTimer = setTimeout(
                        checkStatus,
                        3000
                    );
                }
            }

            if (!cardUid) {
                showMessage("No QR credential detected.");
            } else {
                startVerification();
            }
        </script>
    </body>
    </html>
    """
