
import sys
import cv2
import requests

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QLineEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QAbstractItemView,
    QPlainTextEdit
)

BASE_DIR = Path(__file__).resolve().parent.parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from database.db import (
    initialize_database,
    get_dashboard_stats,
    get_recent_activity,
    get_all_students,
    search_students,
    get_student_by_card,
    log_verification
)


class VerificationWorker(QThread):
    completed = Signal(str, str)

    def __init__(self, student_id, card_uid, image_path):
        super().__init__()
        self.student_id = student_id
        self.card_uid = card_uid
        self.image_path = Path(image_path)

    def run(self):
        from modules.face_verification import verify_face

        try:
            result = verify_face(
                self.student_id,
                self.image_path
            )

            log_verification(
                self.student_id,
                self.card_uid,
                result,
                "Automated face comparison result"
            )

            self.completed.emit(
                result,
                "Face comparison completed. Manual review remains available."
            )

        except Exception as error:
            try:
                log_verification(
                    self.student_id,
                    self.card_uid,
                    "REVIEW",
                    f"Verification error: {error}"
                )
            except Exception:
                pass

            self.completed.emit(
                "REVIEW",
                f"Verification could not be completed: {error}"
            )


class ApiJobPollWorker(QThread):
    job_received = Signal(object)

    def run(self):
        try:
            response = requests.get(
                "http://127.0.0.1:8000/desktop/next-job",
                timeout=0.6
            )
            response.raise_for_status()
            data = response.json()
            job = data.get("job")
            if job is None and data.get("job_id"):
                job = data
            self.job_received.emit(job if isinstance(job, dict) else None)
        except (requests.RequestException, ValueError):
            self.job_received.emit(None)


class ChatWorker(QThread):
    completed = Signal(bool, str)

    def __init__(self, message, history):
        super().__init__()
        self.message = message
        self.history = list(history)

    def run(self):
        try:
            from api.services.ai_service import chat_with_ai

            result = chat_with_ai(self.message, self.history)
            self.completed.emit(
                bool(result.get("success")),
                str(result.get("reply", "The assistant returned no response."))
            )
        except Exception:
            self.completed.emit(
                False,
                "The AI assistant is unavailable. Check that Ollama is running and the configured model is installed."
            )


class SmartGateWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        initialize_database()

        self.current_student = None
        self.worker = None
        self.chat_worker = None
        self.chat_history = []
        self.api_job_id = None
        self.api_poll_worker = None
        self.nav_buttons = {}

        self.camera = None
        self.latest_frame = None

        self.capture_path = (
            BASE_DIR
            / "storage"
            / "student_faces"
            / "live"
            / "current_capture.jpg"
        )

        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(
            self.update_camera_frame
        )

        self.setWindowTitle(
            "SmartGate AI | Identity Verification"
        )

        self.resize(1250, 780)
        self.setMinimumSize(1000, 650)

        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0B1120;
                color: #E5E7EB;
                font-family: Segoe UI;
            }

            QFrame#sidebar {
                background-color: #111827;
                border-right: 1px solid #253247;
            }

            QLabel#brand {
                color: #38BDF8;
                font-size: 24px;
                font-weight: bold;
            }

            QLabel#subtitle {
                color: #94A3B8;
                font-size: 11px;
            }

            QLabel#heading {
                font-size: 27px;
                font-weight: bold;
                color: #F8FAFC;
            }

            QLabel#muted {
                color: #94A3B8;
                font-size: 13px;
            }

            QFrame#panel {
                background-color: #151F32;
                border: 1px solid #26364F;
                border-radius: 12px;
            }

            QLineEdit {
                background-color: #0B1120;
                border: 1px solid #334155;
                border-radius: 7px;
                padding: 12px;
                color: white;
                font-size: 14px;
            }

            QPushButton {
                background-color: #1E293B;
                color: #CBD5E1;
                border: none;
                border-radius: 7px;
                padding: 12px;
                text-align: left;
                font-size: 14px;
            }

            QPushButton:hover {
                background-color: #26364F;
            }

            QPushButton#primary {
                background-color: #0284C7;
                color: white;
                font-weight: bold;
                text-align: center;
            }

            QPushButton#primary:hover {
                background-color: #0369A1;
            }

            QPushButton#activeNav {
                background-color: #123451;
                color: #38BDF8;
                font-weight: bold;
            }

            QPushButton:disabled {
                background-color: #1E293B;
                color: #64748B;
            }

            QLabel#camera {
                background-color: #080D18;
                border: 1px dashed #334155;
                border-radius: 10px;
                color: #64748B;
                font-size: 16px;
            }

            QTableWidget {
                background-color: #151F32;
                alternate-background-color: #19263A;
                color: #E5E7EB;
                border: 1px solid #26364F;
                border-radius: 8px;
                gridline-color: #26364F;
                selection-background-color: #164E73;
            }

            QHeaderView::section {
                background-color: #111827;
                color: #94A3B8;
                padding: 10px;
                border: none;
                font-weight: bold;
            }

            QTableWidget::item {
                padding: 8px;
            }
        """)

        self.build_interface()
        self.refresh_all()

        self.dashboard_timer = QTimer(self)
        self.dashboard_timer.timeout.connect(
            self.refresh_live_data
        )
        self.dashboard_timer.start(3000)

        # The desktop is the only process that opens the webcam.
        # Phone NFC scans are queued by the API and picked up here.
        self.api_poll_timer = QTimer(self)
        self.api_poll_timer.timeout.connect(self.poll_api_for_nfc_job)
        self.api_poll_timer.start(1200)

    def create_label(self, text, name=None):
        label = QLabel(text)

        if name:
            label.setObjectName(name)

        return label

    def create_panel(self):
        panel = QFrame()
        panel.setObjectName("panel")
        return panel

    def build_interface(self):
        central = QWidget()

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(235)

        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(20, 25, 20, 20)
        side_layout.setSpacing(12)

        brand = self.create_label(
            "SMARTGATE AI",
            "brand"
        )

        subtitle = self.create_label(
            "STUDENT IDENTITY SYSTEM",
            "subtitle"
        )

        side_layout.addWidget(brand)
        side_layout.addWidget(subtitle)
        side_layout.addSpacing(35)

        navigation = [
            ("Dashboard", 0),
            ("Verification", 1),
            ("Students", 2),
            ("Activity Logs", 3),
            ("Settings", 4),
            ("AI Assistant", 5)
        ]

        for name, index in navigation:
            button = QPushButton("   " + name)

            button.clicked.connect(
                lambda checked=False, i=index, n=name:
                self.change_page(i, n)
            )

            side_layout.addWidget(button)
            self.nav_buttons[name] = button

        side_layout.addStretch()

        version = self.create_label(
            "SMARTGATE AI  •  v1.0",
            "subtitle"
        )

        side_layout.addWidget(version)

        self.pages = QStackedWidget()

        self.pages.addWidget(self.build_dashboard_page())
        self.pages.addWidget(self.build_verification_page())
        self.pages.addWidget(self.build_students_page())
        self.pages.addWidget(self.build_activity_page())
        self.pages.addWidget(self.build_settings_page())
        self.pages.addWidget(self.build_ai_page())

        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.pages, 1)

        self.setCentralWidget(central)

        self.change_page(0, "Dashboard")

    def build_page(self, title, description):
        page = QWidget()

        layout = QVBoxLayout(page)
        layout.setContentsMargins(35, 30, 35, 25)
        layout.setSpacing(22)

        header = QHBoxLayout()
        heading_box = QVBoxLayout()

        heading = self.create_label(
            title,
            "heading"
        )

        subtitle = self.create_label(
            description,
            "muted"
        )

        heading_box.addWidget(heading)
        heading_box.addWidget(subtitle)

        header.addLayout(heading_box)
        header.addStretch()

        status = self.create_label("● SYSTEM ONLINE")

        status.setStyleSheet(
            "color: #4ADE80; font-weight: bold;"
        )

        header.addWidget(status)
        layout.addLayout(header)

        return page, layout

    def build_dashboard_page(self):
        page, layout = self.build_page(
            "Dashboard Overview",
            "Monitor student records and verification activity."
        )

        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)

        self.stat_labels = {}

        cards = [
            ("Registered Students", "students"),
            ("Total Verifications", "total_verifications"),
            ("Successful", "matches"),
            ("Failed", "mismatches"),
            ("Needs Review", "reviews"),
            ("Pending", "pending")
        ]

        for title, key in cards:
            panel = self.create_panel()

            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(12, 16, 12, 16)
            panel_layout.setSpacing(10)

            panel_title = self.create_label(
                title,
                "muted"
            )

            panel_title.setWordWrap(True)

            value = self.create_label("0")

            value.setAlignment(
                Qt.AlignmentFlag.AlignLeft
            )

            value.setStyleSheet("""
                font-size: 26px;
                font-weight: bold;
                color: #38BDF8;
            """)

            self.stat_labels[key] = value

            panel_layout.addWidget(panel_title)
            panel_layout.addWidget(value)

            stats_layout.addWidget(panel)

        layout.addLayout(stats_layout)

        activity_panel = self.create_panel()

        activity_layout = QVBoxLayout(activity_panel)
        activity_layout.setContentsMargins(18, 18, 18, 18)

        activity_title = self.create_label(
            "Recent Verification Activity"
        )

        activity_title.setStyleSheet(
            "font-size: 17px; font-weight: bold;"
        )

        activity_layout.addWidget(activity_title)

        self.dashboard_table = self.create_table([
            "Student ID",
            "Student Name",
            "Result",
            "Date"
        ])

        activity_layout.addWidget(self.dashboard_table)

        layout.addWidget(activity_panel, 1)

        refresh_button = QPushButton("REFRESH DASHBOARD")
        refresh_button.setObjectName("primary")
        refresh_button.clicked.connect(self.refresh_all)

        layout.addWidget(refresh_button)

        return page

    def build_verification_page(self):
        page, layout = self.build_page(
            "Identity Verification",
            "Look up a student card and perform a face comparison."
        )

        panels = QHBoxLayout()
        panels.setSpacing(18)

        nfc_panel = self.create_panel()

        nfc_layout = QVBoxLayout(nfc_panel)
        nfc_layout.setContentsMargins(20, 20, 20, 20)
        nfc_layout.setSpacing(15)

        nfc_title = self.create_label(
            "01  |  STUDENT CARD"
        )

        nfc_title.setStyleSheet(
            "color: #38BDF8; font-weight: bold;"
        )

        nfc_layout.addWidget(nfc_title)

        nfc_layout.addWidget(
            self.create_label(
                "Enter simulated NFC card UID",
                "muted"
            )
        )

        self.card_input = QLineEdit()
        self.card_input.setPlaceholderText(
            "e.g. uur00602/16"
        )

        nfc_layout.addWidget(self.card_input)

        self.lookup_button = QPushButton(
            "LOOK UP STUDENT CARD"
        )

        self.lookup_button.setObjectName("primary")
        self.lookup_button.clicked.connect(self.lookup_card)

        nfc_layout.addWidget(self.lookup_button)

        self.card_status = self.create_label(
            "Waiting for card...",
            "muted"
        )

        nfc_layout.addWidget(self.card_status)

        self.student_info = self.create_label(
            "Student information will appear here.",
            "muted"
        )

        self.student_info.setWordWrap(True)

        nfc_layout.addWidget(self.student_info)
        nfc_layout.addStretch()

        camera_panel = self.create_panel()

        camera_layout = QVBoxLayout(camera_panel)
        camera_layout.setContentsMargins(20, 20, 20, 20)
        camera_layout.setSpacing(12)

        camera_title = self.create_label(
            "02  |  FACE COMPARISON"
        )

        camera_title.setStyleSheet(
            "color: #38BDF8; font-weight: bold;"
        )

        camera_layout.addWidget(camera_title)

        self.camera_preview = self.create_label(
            "CAMERA PREVIEW\n\nPress START CAMERA to begin."
        )

        self.camera_preview.setObjectName("camera")

        self.camera_preview.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.camera_preview.setMinimumSize(350, 280)

        camera_layout.addWidget(
            self.camera_preview,
            1
        )

        self.camera_status = self.create_label(
            "Camera not started",
            "muted"
        )

        camera_layout.addWidget(self.camera_status)

        camera_buttons = QHBoxLayout()

        self.start_camera_button = QPushButton(
            "START CAMERA"
        )

        self.start_camera_button.setObjectName("primary")
        self.start_camera_button.clicked.connect(
            self.start_camera
        )

        self.capture_button = QPushButton(
            "CAPTURE & VERIFY"
        )

        self.capture_button.setObjectName("primary")
        self.capture_button.setEnabled(False)
        self.capture_button.clicked.connect(
            self.capture_and_verify
        )

        self.stop_camera_button = QPushButton(
            "STOP CAMERA"
        )

        self.stop_camera_button.clicked.connect(
            self.stop_camera
        )

        self.stop_camera_button.setEnabled(False)

        camera_buttons.addWidget(self.start_camera_button)
        camera_buttons.addWidget(self.capture_button)
        camera_buttons.addWidget(self.stop_camera_button)

        camera_layout.addLayout(camera_buttons)

        panels.addWidget(nfc_panel, 1)
        panels.addWidget(camera_panel, 2)

        layout.addLayout(panels, 1)

        result_panel = self.create_panel()

        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(20, 18, 20, 18)

        result_layout.addWidget(
            self.create_label(
                "VERIFICATION RESULT",
                "muted"
            )
        )

        self.result_status = self.create_label(
            "Awaiting verification"
        )

        self.result_status.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: #FBBF24;
        """)

        result_layout.addWidget(self.result_status)

        layout.addWidget(result_panel)

        return page

    def build_students_page(self):
        page, layout = self.build_page(
            "Student Directory",
            "View and search registered student records."
        )

        self.student_search = QLineEdit()

        self.student_search.setPlaceholderText(
            "Search by student ID, name, or department..."
        )

        self.student_search.textChanged.connect(
            self.search_student_records
        )

        layout.addWidget(self.student_search)

        panel = self.create_panel()

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(15, 15, 15, 15)

        self.students_table = self.create_table([
            "Student ID",
            "Full Name",
            "Department",
            "Year",
            "Enrollment"
        ])

        panel_layout.addWidget(self.students_table)

        layout.addWidget(panel, 1)

        refresh_button = QPushButton("REFRESH STUDENTS")
        refresh_button.setObjectName("primary")
        refresh_button.clicked.connect(self.refresh_students)

        layout.addWidget(refresh_button)

        return page

    def build_activity_page(self):
        page, layout = self.build_page(
            "Activity Logs",
            "Review recorded verification events."
        )

        panel = self.create_panel()

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(15, 15, 15, 15)

        self.activity_table = self.create_table([
            "Event ID",
            "Student ID",
            "Student Name",
            "Result",
            "Reason",
            "Timestamp"
        ])

        panel_layout.addWidget(self.activity_table)

        layout.addWidget(panel, 1)

        refresh_button = QPushButton("REFRESH ACTIVITY")
        refresh_button.setObjectName("primary")
        refresh_button.clicked.connect(self.refresh_activity)

        layout.addWidget(refresh_button)

        return page

    def build_settings_page(self):
        page, layout = self.build_page(
            "Settings",
            "SmartGate AI system information."
        )

        panel = self.create_panel()

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(25, 25, 25, 25)
        panel_layout.setSpacing(18)

        settings = [
            ("Application", "SmartGate AI"),
            ("Version", "1.0"),
            ("Database", "SQLite"),
            ("Face Comparison", "DeepFace / FaceNet512"),
            ("Camera", "OpenCV"),
            ("System Status", "Online")
        ]

        for title, value in settings:
            row = QHBoxLayout()

            name = self.create_label(title, "muted")
            detail = self.create_label(value)

            row.addWidget(name)
            row.addStretch()
            row.addWidget(detail)

            panel_layout.addLayout(row)

        layout.addWidget(panel)
        layout.addStretch()

        return page

    def build_ai_page(self):
        page, layout = self.build_page(
            "AI Assistant",
            "Ask about SmartGate features and troubleshooting. The assistant does not make identity or access decisions."
        )

        panel = self.create_panel()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 18, 18, 18)
        panel_layout.setSpacing(12)

        self.chat_transcript = QPlainTextEdit()
        self.chat_transcript.setReadOnly(True)
        self.chat_transcript.setPlaceholderText(
            "SmartGate AI assistant replies will appear here."
        )
        self.chat_transcript.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0B1120;
                border: 1px solid #26364F;
                border-radius: 8px;
                padding: 12px;
                color: #E5E7EB;
                font-size: 14px;
            }
        """)
        panel_layout.addWidget(self.chat_transcript, 1)

        input_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText(
            "Ask a question about SmartGate AI..."
        )
        self.chat_input.returnPressed.connect(self.send_chat_message)

        self.chat_send_button = QPushButton("SEND")
        self.chat_send_button.setObjectName("primary")
        self.chat_send_button.clicked.connect(self.send_chat_message)

        input_row.addWidget(self.chat_input, 1)
        input_row.addWidget(self.chat_send_button)
        panel_layout.addLayout(input_row)

        self.chat_status = self.create_label(
            "Assistant uses the configured local Ollama model.",
            "muted"
        )
        panel_layout.addWidget(self.chat_status)

        clear_button = QPushButton("CLEAR CONVERSATION")
        clear_button.clicked.connect(self.clear_chat)
        panel_layout.addWidget(clear_button)

        layout.addWidget(panel, 1)
        return page

    def send_chat_message(self):
        message = self.chat_input.text().strip()
        if not message:
            return

        if self.chat_worker and self.chat_worker.isRunning():
            return

        self.chat_transcript.appendPlainText(f"You: {message}")
        self.chat_input.clear()
        self.chat_input.setEnabled(False)
        self.chat_send_button.setEnabled(False)
        self.chat_status.setText("Thinking...")

        history_for_request = list(self.chat_history)
        self.chat_history.append({
            "role": "user",
            "content": message
        })
        self.chat_history = self.chat_history[-10:]

        self.chat_worker = ChatWorker(message, history_for_request)
        self.chat_worker.completed.connect(self.on_chat_completed)
        self.chat_worker.start()

    def on_chat_completed(self, success, reply):
        label = "SmartGate AI" if success else "Assistant status"
        self.chat_transcript.appendPlainText(f"{label}: {reply}")

        if success and self.chat_history:
            self.chat_history.append({
                "role": "assistant",
                "content": reply
            })
            self.chat_history = self.chat_history[-10:]

        self.chat_status.setText(
            "Ready" if success else
            "Unavailable — check Ollama and the configured model."
        )
        self.chat_input.setEnabled(True)
        self.chat_send_button.setEnabled(True)
        self.chat_input.setFocus()

        if self.chat_worker:
            self.chat_worker.wait(100)
            self.chat_worker = None

    def clear_chat(self):
        if self.chat_worker and self.chat_worker.isRunning():
            return
        self.chat_history.clear()
        self.chat_transcript.clear()
        self.chat_status.setText("Conversation cleared.")

    def create_table(self, headers):
        table = QTableWidget()

        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)

        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )

        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )

        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)

        return table

    def fill_table(self, table, rows):
        table.setRowCount(0)

        for row_data in rows:
            row_index = table.rowCount()
            table.insertRow(row_index)

            for column, value in enumerate(row_data):
                item = QTableWidgetItem(
                    str(value) if value is not None else "N/A"
                )

                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter
                    | Qt.AlignmentFlag.AlignLeft
                )

                table.setItem(
                    row_index,
                    column,
                    item
                )

    def change_page(self, index, name):
        self.pages.setCurrentIndex(index)

        for button_name, button in self.nav_buttons.items():
            button.setObjectName(
                "activeNav" if button_name == name else ""
            )

            button.style().unpolish(button)
            button.style().polish(button)

        if index == 0:
            self.refresh_dashboard()

        elif index == 2:
            self.refresh_students()

        elif index == 3:
            self.refresh_activity()

    def refresh_all(self):
        self.refresh_dashboard()
        self.refresh_students()
        self.refresh_activity()

    def refresh_live_data(self):
        self.refresh_dashboard(show_errors=False)

        if self.pages.currentIndex() == 3:
            self.refresh_activity(show_errors=False)

    def refresh_dashboard(self, show_errors=True):
        try:
            stats = get_dashboard_stats()

            for key, value in stats.items():
                if key in self.stat_labels:
                    self.stat_labels[key].setText(str(value))

            events = get_recent_activity(8)

            rows = [
                (
                    event["student_id"],
                    event["full_name"] or "Unknown student",
                    event["verification_result"],
                    event["timestamp"]
                )
                for event in events
            ]

            self.fill_table(
                self.dashboard_table,
                rows
            )

        except Exception as error:
            if show_errors:
                QMessageBox.warning(
                    self,
                    "Dashboard Error",
                    str(error)
                )

    def refresh_students(self):
        try:
            students = get_all_students()

            rows = [
                (
                    student["student_id"],
                    student["full_name"],
                    student["department"],
                    student["year_level"],
                    student["enrollment_status"]
                )
                for student in students
            ]

            self.fill_table(
                self.students_table,
                rows
            )

        except Exception as error:
            QMessageBox.warning(
                self,
                "Students Error",
                str(error)
            )

    def search_student_records(self, text):
        try:
            students = search_students(text)

            rows = [
                (
                    student["student_id"],
                    student["full_name"],
                    student["department"],
                    student["year_level"],
                    student["enrollment_status"]
                )
                for student in students
            ]

            self.fill_table(
                self.students_table,
                rows
            )

        except Exception as error:
            QMessageBox.warning(
                self,
                "Search Error",
                str(error)
            )

    def refresh_activity(self, show_errors=True):
        try:
            events = get_recent_activity(100)

            rows = [
                (
                    event["event_id"],
                    event["student_id"],
                    event["full_name"] or "Unknown student",
                    event["verification_result"],
                    event["reason"],
                    event["timestamp"]
                )
                for event in events
            ]

            self.fill_table(
                self.activity_table,
                rows
            )

        except Exception as error:
            if show_errors:
                QMessageBox.warning(
                    self,
                    "Activity Error",
                    str(error)
                )

    def poll_api_for_nfc_job(self):
        if self.api_job_id or self.api_poll_worker and self.api_poll_worker.isRunning():
            return
        if self.worker and self.worker.isRunning():
            return

        self.api_poll_worker = ApiJobPollWorker()
        self.api_poll_worker.job_received.connect(self.on_api_job_received)
        self.api_poll_worker.start()

    def on_api_job_received(self, job):
        if not job:
            self.api_poll_worker = None
            return

        card_uid = str(job.get("card_uid", "")).strip()
        job_id = str(job.get("job_id", "")).strip()
        if not card_uid or not job_id:
            self.api_poll_worker = None
            return

        self.api_job_id = job_id
        self.card_input.setText(card_uid)
        self.card_status.setText("NFC scan received from phone")
        self.result_status.setText(
            "Card scanned — preparing desktop face verification"
        )
        self.lookup_card()

        if self.current_student:
            self.start_camera()
            self.camera_status.setText(
                "Phone NFC scan received. Camera is ready; capture when the student is positioned."
            )
        else:
            self.report_api_job_result(
                "REVIEW",
                "The desktop could not resolve the scanned card in its local database."
            )

        self.api_poll_worker = None

    def report_api_job_result(self, result, message):
        job_id = self.api_job_id
        self.api_job_id = None
        if not job_id:
            return
        try:
            requests.post(
                "http://127.0.0.1:8000/desktop/verification-result/"
                + job_id,
                json={"result": result, "message": message},
                timeout=1.5
            ).raise_for_status()
        except requests.RequestException:
            QMessageBox.warning(
                self,
                "API Connection",
                "The local verification result was saved, but the phone status could not be updated. Check that the SmartGate API is running."
            )

    def lookup_card(self):
        card_uid = self.card_input.text().strip()

        if not card_uid:
            QMessageBox.warning(
                self,
                "Missing Card UID",
                "Please enter a student card UID."
            )
            return

        if self.camera is not None:
            self.stop_camera()

        try:
            student = get_student_by_card(card_uid)

            if not student:
                self.current_student = None
                self.capture_button.setEnabled(False)

                self.card_status.setText("Unknown card")

                self.student_info.setText(
                    "No registered student was found for this card."
                )

                return

            self.current_student = dict(student)

            self.card_status.setText(
                "Student record found"
            )

            self.student_info.setText(
                f"Student ID: {student['student_id']}\n"
                f"Name: {student['full_name']}\n"
                f"Department: {student['department']}\n"
                f"Year: {student['year_level']}\n"
                f"Enrollment: {student['enrollment_status']}"
            )

            self.capture_button.setEnabled(False)

            self.result_status.setText(
                "Ready for face comparison"
            )

            self.result_status.setStyleSheet("""
                font-size: 20px;
                font-weight: bold;
                color: #FBBF24;
            """)

        except Exception as error:
            QMessageBox.critical(
                self,
                "Card Lookup Error",
                str(error)
            )

    def start_camera(self):
        if not self.current_student:
            QMessageBox.warning(
                self,
                "No Student",
                "Look up a registered student card first."
            )
            return

        if self.worker and self.worker.isRunning():
            return

        if self.camera is not None:
            return

        self.camera_status.setText(
            "Connecting to camera..."
        )

        self.camera = cv2.VideoCapture(
            0,
            cv2.CAP_DSHOW
        )

        if not self.camera.isOpened():
            self.camera.release()
            self.camera = None

            self.camera_status.setText(
                "Camera could not be opened"
            )

            QMessageBox.warning(
                self,
                "Camera Error",
                "Could not access your webcam. Check that it is connected and not being used by another application."
            )

            return

        self.camera.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            640
        )

        self.camera.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            480
        )

        self.camera_status.setText(
            "Camera active"
        )

        self.start_camera_button.setEnabled(False)
        self.stop_camera_button.setEnabled(True)
        self.capture_button.setEnabled(True)
        self.lookup_button.setEnabled(False)
        self.card_input.setEnabled(False)

        self.camera_timer.start(30)

    def update_camera_frame(self):
        if self.camera is None:
            return

        success, frame = self.camera.read()

        if not success:
            self.camera_status.setText(
                "Unable to read camera frame"
            )
            return

        self.latest_frame = frame.copy()

        rgb_frame = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2RGB
        )

        height, width, channels = rgb_frame.shape
        bytes_per_line = channels * width

        image = QImage(
            rgb_frame.data,
            width,
            height,
            bytes_per_line,
            QImage.Format.Format_RGB888
        )

        pixmap = QPixmap.fromImage(image)

        self.camera_preview.setPixmap(
            pixmap.scaled(
                self.camera_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )

    def stop_camera(self):
        self.camera_timer.stop()

        if self.camera is not None:
            self.camera.release()
            self.camera = None

        self.latest_frame = None

        if hasattr(self, "camera_preview"):
            self.camera_preview.clear()

            self.camera_preview.setText(
                "CAMERA PREVIEW\n\nPress START CAMERA to begin."
            )

        if hasattr(self, "camera_status"):
            self.camera_status.setText(
                "Camera stopped"
            )

        if hasattr(self, "start_camera_button"):
            self.start_camera_button.setEnabled(
                self.current_student is not None
                and not (
                    self.worker and self.worker.isRunning()
                )
            )

        if hasattr(self, "stop_camera_button"):
            self.stop_camera_button.setEnabled(False)

        if hasattr(self, "capture_button"):
            self.capture_button.setEnabled(False)

        if hasattr(self, "lookup_button"):
            self.lookup_button.setEnabled(
                not (self.worker and self.worker.isRunning())
            )

        if hasattr(self, "card_input"):
            self.card_input.setEnabled(
                not (self.worker and self.worker.isRunning())
            )

    def capture_and_verify(self):
        if not self.current_student:
            QMessageBox.warning(
                self,
                "No Student",
                "Look up a student card first."
            )
            return

        if self.latest_frame is None:
            QMessageBox.warning(
                self,
                "No Camera Frame",
                "Start the camera and wait for the preview before capturing."
            )
            return

        if self.worker and self.worker.isRunning():
            return

        try:
            self.capture_path.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            saved = cv2.imwrite(
                str(self.capture_path),
                self.latest_frame
            )

            if not saved:
                raise RuntimeError(
                    "Could not save the captured image."
                )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Capture Error",
                str(error)
            )
            return

        student_id = self.current_student["student_id"]
        card_uid = self.card_input.text().strip()

        self.stop_camera()

        self.start_camera_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        self.stop_camera_button.setEnabled(False)
        self.lookup_button.setEnabled(False)
        self.card_input.setEnabled(False)

        self.camera_status.setText(
            "Image captured. Comparing faces..."
        )

        self.camera_preview.setText(
            "CAPTURE SAVED\n\nFace comparison is running."
        )

        self.result_status.setText(
            "Verification in progress..."
        )

        self.result_status.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: #38BDF8;
        """)

        self.worker = VerificationWorker(
            student_id,
            card_uid,
            self.capture_path
        )

        self.worker.completed.connect(
            self.on_verification_completed
        )

        self.worker.start()

    def start_verification(self):
        self.start_camera()

    def on_verification_completed(self, result, message):
        self.result_status.setText(result)

        if result == "MATCH":
            color = "#4ADE80"
        elif result == "MISMATCH":
            color = "#F87171"
        else:
            color = "#FBBF24"

        self.result_status.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {color};"
        )

        self.camera_status.setText(
            "Face comparison completed"
        )

        self.camera_preview.clear()

        self.camera_preview.setText(
            "CAPTURE COMPLETE\n\nSee verification result below."
        )

        self.lookup_button.setEnabled(True)
        self.card_input.setEnabled(True)

        self.start_camera_button.setEnabled(
            self.current_student is not None
        )

        self.capture_button.setEnabled(False)
        self.stop_camera_button.setEnabled(False)

        self.refresh_all()
        self.report_api_job_result(result, message)

        QMessageBox.information(
            self,
            "Verification Complete",
            f"Result: {result}\n\n{message}"
        )

        self.worker = None

    def closeEvent(self, event):
        self.dashboard_timer.stop()
        self.api_poll_timer.stop()
        self.stop_camera()

        if self.worker and self.worker.isRunning():
            self.worker.wait()

        if self.chat_worker and self.chat_worker.isRunning():
            self.chat_worker.wait()

        if self.api_poll_worker and self.api_poll_worker.isRunning():
            self.api_poll_worker.wait(800)

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = SmartGateWindow()
    window.show()

    sys.exit(app.exec())
