import glob
import os
import sys
import threading
import time
from datetime import datetime
import cv2
import numpy as np

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QLineEdit,
    QFrame,
    QMessageBox,
)

from data_model import get_sentence_id_str


def detect_camera_indices(max_to_check=5):
    """Detect available, working camera indices."""
    working = []
    devs = sorted(glob.glob("/dev/video*"))
    candidates = []
    for d in devs:
        try:
            candidates.append(int(d.replace("/dev/video", "")))
        except ValueError:
            pass
    if not candidates:
        candidates = list(range(max_to_check))

    for idx in candidates[:max_to_check]:
        cap = None
        try:
            if sys.platform.startswith("linux"):
                cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            else:
                cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    working.append(idx)
        except Exception:
            pass
        finally:
            if cap is not None:
                cap.release()
    return working if working else [0]


class CameraThread(QThread):
    """Worker thread that continuously captures frames from OpenCV VideoCapture,
    crops to 1:1 square aspect ratio matching the smallest side,
    optionally flips horizontally, and writes them at a constant 30.0 FPS.
    """

    frame_ready = pyqtSignal(np.ndarray)
    camera_status = pyqtSignal(bool, str)
    recording_started = pyqtSignal()
    recording_tick = pyqtSignal(int, float)  # frame_count, elapsed_seconds
    recording_finished = pyqtSignal(str, int, float)  # path, frame_count, duration
    recording_error = pyqtSignal(str)

    def __init__(self, camera_index=0, flip_horizontal=False):
        super().__init__()
        self.camera_index = camera_index
        self.flip_horizontal = flip_horizontal
        self.running = True

        self._lock = threading.Lock()
        self._cmd_start_recording = False
        self._cmd_stop_recording = False
        self._target_path = ""

        self.is_recording = False

    def set_camera_index(self, index):
        self.camera_index = index

    def set_flip_horizontal(self, enabled):
        with self._lock:
            self.flip_horizontal = enabled

    def start_recording(self, file_path):
        with self._lock:
            self._target_path = file_path
            self._cmd_start_recording = True
            self._cmd_stop_recording = False

    def stop_recording(self):
        with self._lock:
            self._cmd_stop_recording = True

    def stop_thread(self):
        self.running = False
        self.wait(1500)

    def run(self):
        cap = None
        try:
            if sys.platform.startswith("linux"):
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
                if not cap.isOpened():
                    cap.release()
                    cap = cv2.VideoCapture(self.camera_index)
            else:
                cap = cv2.VideoCapture(self.camera_index)
        except Exception as e:
            self.camera_status.emit(False, f"Failed to initialize camera: {e}")
            return

        if not cap.isOpened():
            self.camera_status.emit(
                False,
                f"Camera {self.camera_index} not detected or currently in use.",
            )
            if cap:
                cap.release()
            return

        # Attempt to request MJPG and 30 FPS from camera hardware/driver
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_FPS, 30.0)
        except Exception:
            pass

        native_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        native_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if native_w <= 0 or native_h <= 0:
            ret, test_f = cap.read()
            if ret and test_f is not None:
                native_h, native_w = test_f.shape[:2]
            else:
                native_w, native_h = 640, 480

        side = min(native_w, native_h)
        target_fps = 30.0

        self.camera_status.emit(
            True,
            f"Camera active (Native: {native_w}x{native_h} -> 1:1 Crop: {side}x{side} @ {int(target_fps)}fps)",
        )

        writer = None
        recorded_frames = 0
        record_start_time = 0.0
        active_path = ""
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        while self.running:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.005)
                continue

            # 1. Perform 1:1 square crop centered on the frame
            h, w = frame.shape[:2]
            curr_side = min(h, w)
            y1 = (h - curr_side) // 2
            y2 = y1 + curr_side
            x1 = (w - curr_side) // 2
            x2 = x1 + curr_side
            proc_frame = frame[y1:y2, x1:x2]

            # 2. Apply horizontal flip if enabled
            with self._lock:
                do_flip = self.flip_horizontal
            if do_flip:
                proc_frame = cv2.flip(proc_frame, 1)

            # Check if recording start was requested
            if self._cmd_start_recording:
                with self._lock:
                    active_path = self._target_path
                    self._cmd_start_recording = False
                    self.is_recording = True
                    recorded_frames = 0
                    record_start_time = time.time()

                    os.makedirs(
                        os.path.dirname(os.path.abspath(active_path)),
                        exist_ok=True,
                    )

                    sq_h, sq_w = proc_frame.shape[:2]
                    writer = cv2.VideoWriter(
                        active_path, fourcc, target_fps, (sq_w, sq_h)
                    )
                    if not writer.isOpened():
                        self.is_recording = False
                        writer = None
                        self.recording_error.emit(
                            f"Failed to open video writer for {active_path}"
                        )
                    else:
                        # Write the first frame immediately as frame 0
                        writer.write(proc_frame)
                        recorded_frames = 1
                        self.recording_started.emit()

            # If recording is active, write frames with 30fps real-time pacing
            elif self.is_recording and writer is not None:
                elapsed = time.time() - record_start_time
                expected_frames = int(elapsed * target_fps) + 1

                # If camera is 60fps (or faster than 30fps), expected_frames has not advanced yet:
                # we skip writing this frame (clamps 60fps to 30fps).
                # If camera dropped frames or is slower than 30fps, we catch up so playback is 1:1 real-time.
                if expected_frames > recorded_frames:
                    missing = min(expected_frames - recorded_frames, 10)
                    for _ in range(missing):
                        writer.write(proc_frame)
                        recorded_frames += 1

                self.recording_tick.emit(recorded_frames, elapsed)

            # Check if recording stop was requested
            if self._cmd_stop_recording:
                with self._lock:
                    self._cmd_stop_recording = False
                    if self.is_recording and writer is not None:
                        writer.release()
                        writer = None
                        self.is_recording = False
                        elapsed = time.time() - record_start_time
                        self.recording_finished.emit(
                            active_path, recorded_frames, elapsed
                        )

            # Convert BGR frame to RGB for Qt rendering
            rgb_frame = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2RGB)
            self.frame_ready.emit(rgb_frame)

        # Cleanup on exit
        if writer is not None:
            writer.release()
            writer = None
        cap.release()


class CameraRecorderWindow(QWidget):
    """Independent window allowing live camera preview, countdown timing,

    and capturing PJM signing videos.
    """

    video_recorded = pyqtSignal(str, int, float)  # path, frame_count, duration
    annotate_requested = pyqtSignal(str, int, float)  # path, frame_count, duration
    user_id_changed = pyqtSignal(str)  # user_id

    STATE_IDLE = "idle"
    STATE_COUNTDOWN = "countdown"
    STATE_RECORDING = "recording"
    STATE_FINISHED = "finished"
    STATE_PREVIEWING = "previewing"

    def __init__(
        self, parent=None, dataset_info=None, original_glosses=None, user_id=None
    ):
        super().__init__(parent, Qt.WindowType.Window)
        self.dataset_info = dataset_info or {}
        self.original_glosses = original_glosses or []
        self.user_id = str(user_id).strip() if user_id else ""

        self.state = self.STATE_IDLE
        self.camera_thread = None
        self.flip_horizontal = False
        self.current_countdown = 3
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._on_countdown_tick)

        self.recorded_video_path = None
        self.recorded_frame_count = 0
        self.recorded_duration = 0.0

        # Video preview playback timer for reviewing recording
        self._preview_cap = None
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._on_preview_tick)

        self.setWindowTitle("Camera Recording Module - PJM Signing")
        self.resize(760, 680)
        self.setStyleSheet(
            "QWidget { background-color: #242424; color: #ffffff; font-family: 'Segoe UI', sans-serif; }"
            "QLabel { color: #ffffff; }"
        )

        self.init_ui()
        self.start_camera()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # Header: Reference Info Card
        header_card = QFrame()
        header_card.setStyleSheet(
            "QFrame {"
            "  background-color: #323232;"
            "  border: 1px solid #4a4a4a;"
            "  border-radius: 6px;"
            "  padding: 8px 12px;"
            "}"
        )
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(6, 6, 6, 6)
        header_layout.setSpacing(4)

        sentence_text = self.dataset_info.get("sentence", "")
        dataset_name = self.dataset_info.get("name", "Unknown Video")

        title_label = QLabel("🎯 Reference Sentence to Sign:")
        title_label.setStyleSheet("color: #90caf9; font-size: 11px; font-weight: bold; text-transform: uppercase;")
        header_layout.addWidget(title_label)

        sentence_display = sentence_text if sentence_text else dataset_name
        self.sentence_label = QLabel(sentence_display)
        self.sentence_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff;")
        self.sentence_label.setWordWrap(True)
        header_layout.addWidget(self.sentence_label)

        if self.original_glosses:
            ref_glosses = [g for g in self.original_glosses if g != "EoR"]
            if ref_glosses:
                glosses_label = QLabel(f"Glosses: {' → '.join(ref_glosses)}")
                glosses_label.setStyleSheet("font-size: 12px; color: #ffb74d; font-weight: bold;")
                glosses_label.setWordWrap(True)
                header_layout.addWidget(glosses_label)

        main_layout.addWidget(header_card)

        # Video Preview Viewport Container
        self.video_container = QWidget()
        self.video_container.setMinimumSize(640, 400)
        self.video_container.setStyleSheet("background-color: #111111; border-radius: 6px;")
        video_layout = QVBoxLayout(self.video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)

        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: transparent;")
        self.video_label.setText("Initializing camera feed...")
        video_layout.addWidget(self.video_label)

        # Overlay: Recording Badge (Top-Left)
        self.rec_badge = QLabel(self.video_container)
        self.rec_badge.setStyleSheet(
            "QLabel {"
            "  background-color: rgba(229, 57, 53, 0.9);"
            "  color: white;"
            "  font-size: 13px;"
            "  font-weight: bold;"
            "  border-radius: 4px;"
            "  padding: 4px 10px;"
            "}"
        )
        self.rec_badge.setText("● REC 00:00.0 (0 frames)")
        self.rec_badge.move(14, 14)
        self.rec_badge.hide()

        # Overlay: Big Countdown Number in the Center
        self.countdown_overlay = QLabel(self.video_container)
        self.countdown_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_overlay.setStyleSheet(
            "QLabel {"
            "  background-color: rgba(0, 0, 0, 0.7);"
            "  color: #FFEB3B;"
            "  font-size: 72px;"
            "  font-weight: bold;"
            "  border: 4px solid #FFEB3B;"
            "  border-radius: 65px;"
            "}"
        )
        self.countdown_overlay.setFixedSize(130, 130)
        self.countdown_overlay.hide()

        main_layout.addWidget(self.video_container, stretch=1)

        # Controls & Settings Bar
        controls_card = QFrame()
        controls_card.setStyleSheet(
            "QFrame {"
            "  background-color: #2e2e2e;"
            "  border: 1px solid #424242;"
            "  border-radius: 6px;"
            "  padding: 8px 12px;"
            "}"
        )
        controls_layout = QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(8, 6, 8, 6)
        controls_layout.setSpacing(12)

        # User ID Input (Mandatory for recording)
        id_label = QLabel("👤 Your ID:")
        id_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #64b5f6;")
        controls_layout.addWidget(id_label)

        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText("e.g. 7")
        self.user_id_input.setText(self.user_id)
        self.user_id_input.setFixedWidth(75)
        self.user_id_input.setStyleSheet(
            "QLineEdit {"
            "  background-color: #3e3e3e;"
            "  color: #64b5f6;"
            "  font-weight: bold;"
            "  font-size: 13px;"
            "  padding: 4px 8px;"
            "  border-radius: 4px;"
            "  border: 1px solid #64b5f6;"
            "}"
        )
        self.user_id_input.setToolTip("Your Person / User ID (replaces reference person ID in filename)")
        self.user_id_input.textChanged.connect(self._on_user_id_edited)
        controls_layout.addWidget(self.user_id_input)

        controls_layout.addSpacing(10)

        # Camera selection dropdown
        cam_label = QLabel("Camera:")
        cam_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        controls_layout.addWidget(cam_label)

        self.cam_combo = QComboBox()
        self.cam_combo.setStyleSheet(
            "QComboBox { background-color: #3e3e3e; color: white; padding: 4px 8px; border-radius: 4px; }"
            "QComboBox::drop-down { border: none; }"
        )
        self.cam_combo.currentIndexChanged.connect(self._on_camera_selection_changed)
        controls_layout.addWidget(self.cam_combo)

        self.refresh_cams_btn = QPushButton("🔄")
        self.refresh_cams_btn.setToolTip("Scan for cameras")
        self.refresh_cams_btn.setStyleSheet("background-color: #444; padding: 4px 8px; border-radius: 4px;")
        self.refresh_cams_btn.clicked.connect(self.populate_camera_list)
        controls_layout.addWidget(self.refresh_cams_btn)

        controls_layout.addSpacing(16)

        # Countdown Timer Setting
        timer_label = QLabel("Countdown Delay:")
        timer_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        controls_layout.addWidget(timer_label)

        self.countdown_spin = QSpinBox()
        self.countdown_spin.setRange(0, 30)
        self.countdown_spin.setValue(3)
        self.countdown_spin.setSuffix(" sec")
        self.countdown_spin.setStyleSheet(
            "QSpinBox { background-color: #3e3e3e; color: white; padding: 4px 8px; font-weight: bold; font-size: 13px; border-radius: 4px; }"
        )
        self.countdown_spin.setToolTip(
            "Seconds to count down before recording starts. The frame immediately after countdown stops is recorded as frame 0."
        )
        controls_layout.addWidget(self.countdown_spin)

        controls_layout.addSpacing(16)

        # Horizontal Flip Checkbox (Mirror)
        self.flip_checkbox = QCheckBox("↔ Flip Horizontally")
        self.flip_checkbox.setStyleSheet(
            "QCheckBox { color: white; font-size: 13px; font-weight: bold; spacing: 6px; }"
            "QCheckBox::indicator { width: 16px; height: 16px; }"
        )
        self.flip_checkbox.setToolTip(
            "Mirror camera horizontally (affects both live preview and resulting recorded frames)"
        )
        self.flip_checkbox.setChecked(self.flip_horizontal)
        self.flip_checkbox.toggled.connect(self._on_flip_toggled)
        controls_layout.addWidget(self.flip_checkbox)

        controls_layout.addStretch()

        # Action Buttons
        self.action_btn = QPushButton("🔴 Start Recording")
        self.action_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #e53935;"
            "  color: white;"
            "  font-size: 14px;"
            "  font-weight: bold;"
            "  padding: 8px 24px;"
            "  border-radius: 5px;"
            "  border: none;"
            "}"
            "QPushButton:hover { background-color: #d32f2f; }"
            "QPushButton:disabled { background-color: #555555; color: #888888; }"
        )
        self.action_btn.clicked.connect(self.on_action_clicked)
        controls_layout.addWidget(self.action_btn)

        main_layout.addWidget(controls_card)

        # Post-recording action bar (hidden initially)
        self.post_record_card = QFrame()
        self.post_record_card.setStyleSheet(
            "QFrame {"
            "  background-color: #1e392a;"
            "  border: 1px solid #2e7d32;"
            "  border-radius: 6px;"
            "  padding: 6px 12px;"
            "}"
        )
        post_layout = QHBoxLayout(self.post_record_card)
        post_layout.setContentsMargins(8, 4, 8, 4)

        self.summary_label = QLabel("✅ Recording saved!")
        self.summary_label.setStyleSheet("color: #a5d6a7; font-weight: bold; font-size: 13px;")
        post_layout.addWidget(self.summary_label)

        post_layout.addStretch()

        self.preview_btn = QPushButton("▶ Preview Video")
        self.preview_btn.setStyleSheet("background-color: #388e3c; color: white; padding: 6px 14px; font-weight: bold; border-radius: 4px;")
        self.preview_btn.clicked.connect(self.toggle_preview_playback)
        post_layout.addWidget(self.preview_btn)

        self.rerecord_btn = QPushButton("🔄 Record Again")
        self.rerecord_btn.setStyleSheet("background-color: #f57c00; color: white; padding: 6px 14px; font-weight: bold; border-radius: 4px;")
        self.rerecord_btn.clicked.connect(self.reset_to_idle)
        post_layout.addWidget(self.rerecord_btn)

        self.annotate_btn = QPushButton("✏️ Annotate")
        self.annotate_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #2e7d32;"
            "  color: white;"
            "  padding: 6px 20px;"
            "  font-weight: bold;"
            "  font-size: 13px;"
            "  border-radius: 4px;"
            "}"
            "QPushButton:hover { background-color: #388e3c; }"
        )
        self.annotate_btn.setToolTip("Open this recorded video in the annotation interface.")
        self.annotate_btn.clicked.connect(self.request_annotation)
        post_layout.addWidget(self.annotate_btn)

        self.post_record_card.hide()
        main_layout.addWidget(self.post_record_card)

        # Status Bar
        self.status_label = QLabel("Checking camera devices...")
        self.status_label.setStyleSheet("color: #9e9e9e; font-size: 12px;")
        main_layout.addWidget(self.status_label)

        self.populate_camera_list()

    def _on_user_id_edited(self, text):
        self.user_id = text.strip()
        self._update_action_btn_state()
        self.user_id_changed.emit(self.user_id)

    def set_user_id(self, user_id):
        self.user_id = str(user_id).strip() if user_id else ""
        if self.user_id_input.text().strip() != self.user_id:
            self.user_id_input.blockSignals(True)
            self.user_id_input.setText(self.user_id)
            self.user_id_input.blockSignals(False)
        self._update_action_btn_state()

    def _update_action_btn_state(self):
        if self.state != self.STATE_IDLE:
            return
        has_cams = self.cam_combo.count() > 0
        has_user_id = bool(self.user_id)

        if not has_user_id:
            self.action_btn.setEnabled(False)
            self.action_btn.setToolTip("Please enter your User ID above to enable recording.")
            self.status_label.setText("⚠️ Please enter your User ID above to enable recording.")
        elif not has_cams:
            self.action_btn.setEnabled(False)
            self.action_btn.setToolTip("No camera detected.")
            self.status_label.setText("⚠️ No working camera devices found.")
        else:
            self.action_btn.setEnabled(True)
            self.action_btn.setToolTip(f"Start recording as Person ID {self.user_id}")
            self.status_label.setText(
                f"🟢 Ready to record as Person ID {self.user_id}. Press 'Start Recording' when prepared."
            )

    def populate_camera_list(self):
        self.cam_combo.blockSignals(True)
        self.cam_combo.clear()
        detected = detect_camera_indices(max_to_check=4)
        for idx in detected:
            self.cam_combo.addItem(f"Camera {idx}", idx)
        self.cam_combo.blockSignals(False)
        self._update_action_btn_state()

    def start_camera(self):
        if self.cam_combo.count() == 0:
            return

        cam_idx = self.cam_combo.currentData()
        if cam_idx is None:
            cam_idx = 0

        self.stop_camera()

        self.camera_thread = CameraThread(
            camera_index=cam_idx, flip_horizontal=self.flip_horizontal
        )
        self.camera_thread.frame_ready.connect(self.on_frame_received)
        self.camera_thread.camera_status.connect(self.on_camera_status)
        self.camera_thread.recording_started.connect(self.on_recording_started)
        self.camera_thread.recording_tick.connect(self.on_recording_tick)
        self.camera_thread.recording_finished.connect(self.on_recording_finished)
        self.camera_thread.recording_error.connect(self.on_recording_error)
        self.camera_thread.start()

    def stop_camera(self):
        if self.camera_thread and self.camera_thread.isRunning():
            self.camera_thread.stop_thread()
            self.camera_thread = None

    def _on_flip_toggled(self, checked):
        self.flip_horizontal = checked
        if self.camera_thread:
            self.camera_thread.set_flip_horizontal(checked)

    def _on_camera_selection_changed(self, _):
        if self.state in (self.STATE_COUNTDOWN, self.STATE_RECORDING):
            return
        self.start_camera()

    def on_frame_received(self, rgb_frame):
        if self.state == self.STATE_PREVIEWING:
            return

        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        self.video_label.setPixmap(
            pixmap.scaled(
                self.video_container.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def on_camera_status(self, is_connected, message):
        if is_connected:
            self._update_action_btn_state()
        else:
            self.status_label.setText(f"🔴 {message}")
            self.action_btn.setEnabled(False)
            self.video_label.setText(f"⚠️ {message}\nPlease plug in a camera and click 🔄")

    def on_action_clicked(self):
        if self.state == self.STATE_IDLE:
            if not self.user_id:
                QMessageBox.warning(
                    self,
                    "User ID Required",
                    "⚠️ Recording cannot start without a User ID.\n\nPlease enter your ID above.",
                )
                self.user_id_input.setFocus()
                return

            countdown_val = self.countdown_spin.value()
            if countdown_val > 0:
                self.start_countdown(countdown_val)
            else:
                self.start_actual_recording()

        elif self.state == self.STATE_COUNTDOWN:
            self.cancel_countdown()

        elif self.state == self.STATE_RECORDING:
            self.stop_actual_recording()

        elif self.state == self.STATE_FINISHED:
            self.reset_to_idle()

    def start_countdown(self, seconds):
        if not self.user_id:
            QMessageBox.warning(
                self,
                "User ID Required",
                "⚠️ Recording cannot start without a User ID.\n\nPlease enter your ID above.",
            )
            self.user_id_input.setFocus()
            self.reset_to_idle()
            return

        self.state = self.STATE_COUNTDOWN
        self.current_countdown = seconds

        self.user_id_input.setEnabled(False)
        self.countdown_spin.setEnabled(False)
        self.cam_combo.setEnabled(False)
        self.refresh_cams_btn.setEnabled(False)
        self.flip_checkbox.setEnabled(False)

        self.action_btn.setText("✖ Cancel Countdown")
        self.action_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #757575;"
            "  color: white;"
            "  font-size: 14px;"
            "  font-weight: bold;"
            "  padding: 8px 24px;"
            "  border-radius: 5px;"
            "}"
            "QPushButton:hover { background-color: #616161; }"
        )

        self.countdown_overlay.setText(str(self.current_countdown))
        self._position_overlays()
        self.countdown_overlay.show()

        self.status_label.setText(f"⏳ Get ready! Recording starts in {self.current_countdown} seconds...")
        self.countdown_timer.start(1000)

    def _on_countdown_tick(self):
        self.current_countdown -= 1
        if self.current_countdown > 0:
            self.countdown_overlay.setText(str(self.current_countdown))
            self.status_label.setText(f"⏳ Get ready! Recording starts in {self.current_countdown} seconds...")
        else:
            self.countdown_timer.stop()
            self.countdown_overlay.hide()
            self.start_actual_recording()

    def cancel_countdown(self):
        self.countdown_timer.stop()
        self.countdown_overlay.hide()
        self.reset_to_idle()
        self.status_label.setText("Countdown cancelled. Ready when you are.")

    def start_actual_recording(self):
        if not self.user_id:
            QMessageBox.warning(
                self,
                "User ID Required",
                "⚠️ Recording cannot start without a User ID.\n\nPlease enter your ID above.",
            )
            self.user_id_input.setFocus()
            self.reset_to_idle()
            return

        if not self.camera_thread:
            QMessageBox.warning(self, "Error", "Camera is not connected.")
            self.reset_to_idle()
            return

        self.state = self.STATE_RECORDING
        self.user_id_input.setEnabled(False)
        self.countdown_spin.setEnabled(False)
        self.cam_combo.setEnabled(False)
        self.refresh_cams_btn.setEnabled(False)
        self.flip_checkbox.setEnabled(False)

        self.action_btn.setText("⏹ Stop Recording")
        self.action_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #b71c1c;"
            "  color: white;"
            "  font-size: 14px;"
            "  font-weight: bold;"
            "  padding: 8px 24px;"
            "  border-radius: 5px;"
            "}"
            "QPushButton:hover { background-color: #c62828; }"
        )

        # Pattern: ID_SENTENCEID_DATE_TIME (example: 6_01_20260319_172851)
        sentence_id_str = get_sentence_id_str(self.dataset_info)
        date_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{self.user_id}_{sentence_id_str}_{date_time_str}"
        target_dir = os.path.join(os.getcwd(), "recordings")
        os.makedirs(target_dir, exist_ok=True)
        filename = f"{base_name}.mp4"
        target_path = os.path.join(target_dir, filename)

        self.rec_badge.setText("● REC 00:00.0 (0 frames)")
        self._position_overlays()
        self.rec_badge.show()

        self.status_label.setText("🔴 Recording started! Sign your sentence now...")
        # Start recording immediately - the first captured frame will be frame 0
        self.camera_thread.start_recording(target_path)

    def on_recording_started(self):
        self.status_label.setText("🔴 Recording active! First frame captured.")

    def on_recording_tick(self, frame_count, elapsed_seconds):
        min_part = int(elapsed_seconds // 60)
        sec_part = elapsed_seconds % 60
        self.rec_badge.setText(f"● REC {min_part:02d}:{sec_part:04.1f} ({frame_count} frames)")
        self.rec_badge.adjustSize()

    def stop_actual_recording(self):
        if self.camera_thread:
            self.status_label.setText("Finalizing video file...")
            self.camera_thread.stop_recording()

    def on_recording_finished(self, file_path, frame_count, duration):
        self.state = self.STATE_FINISHED
        self.rec_badge.hide()

        self.recorded_video_path = file_path
        self.recorded_frame_count = frame_count
        self.recorded_duration = duration

        self.summary_label.setText(
            f"✅ Video recorded: {os.path.basename(file_path)} ({frame_count} frames, {duration:.1f}s)"
        )
        self.post_record_card.show()

        self.action_btn.setText("🔄 Record Again")
        self.action_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #f57c00;"
            "  color: white;"
            "  font-size: 14px;"
            "  font-weight: bold;"
            "  padding: 8px 24px;"
            "  border-radius: 5px;"
            "}"
            "QPushButton:hover { background-color: #ef6c00; }"
        )

        self.status_label.setText(
            f"Recording completed! Saved to {file_path}. Click 'Preview Video' to inspect or 'Record Again' for another take."
        )

        self.video_recorded.emit(file_path, frame_count, duration)

    def on_recording_error(self, err_msg):
        self.rec_badge.hide()
        QMessageBox.critical(self, "Recording Error", err_msg)
        self.reset_to_idle()

    def reset_to_idle(self):
        self.stop_preview_playback()
        self.state = self.STATE_IDLE
        self.countdown_timer.stop()
        self.countdown_overlay.hide()
        self.rec_badge.hide()
        self.post_record_card.hide()

        self.user_id_input.setEnabled(True)
        self.countdown_spin.setEnabled(True)
        self.cam_combo.setEnabled(True)
        self.refresh_cams_btn.setEnabled(True)
        self.flip_checkbox.setEnabled(True)

        self.action_btn.setText("🔴 Start Recording")
        self.action_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #e53935;"
            "  color: white;"
            "  font-size: 14px;"
            "  font-weight: bold;"
            "  padding: 8px 24px;"
            "  border-radius: 5px;"
            "}"
            "QPushButton:hover { background-color: #d32f2f; }"
        )
        self._update_action_btn_state()

    # --- Video Preview Playback of Newly Recorded Clip ---
    def toggle_preview_playback(self):
        if self.state == self.STATE_PREVIEWING:
            self.stop_preview_playback()
        else:
            self.start_preview_playback()

    def start_preview_playback(self):
        if not self.recorded_video_path or not os.path.exists(self.recorded_video_path):
            QMessageBox.warning(self, "Preview", "No recorded video found to preview.")
            return

        self.stop_preview_playback()
        self._preview_cap = cv2.VideoCapture(self.recorded_video_path)
        if not self._preview_cap.isOpened():
            QMessageBox.critical(self, "Preview Error", "Could not open recorded video file.")
            self._preview_cap = None
            return

        fps = self._preview_cap.get(cv2.CAP_PROP_FPS) or 30.0
        interval_ms = max(10, int(round(1000.0 / fps)))

        self.state = self.STATE_PREVIEWING
        self.preview_btn.setText("⏹ Stop Preview")
        self.preview_btn.setStyleSheet("background-color: #c62828; color: white; padding: 6px 14px; font-weight: bold; border-radius: 4px;")
        self.status_label.setText(f"Playing back preview of {os.path.basename(self.recorded_video_path)} at {fps:.0f} FPS...")

        self._preview_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._preview_timer.start(interval_ms)

    def _on_preview_tick(self):
        if not self._preview_cap:
            self.stop_preview_playback()
            return

        ret, frame = self._preview_cap.read()
        if not ret or frame is None:
            # End of video: loop back to beginning
            self._preview_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._preview_cap.read()
            if not ret or frame is None:
                self.stop_preview_playback()
                return

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)

        self.video_label.setPixmap(
            pixmap.scaled(
                self.video_container.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def stop_preview_playback(self):
        self._preview_timer.stop()
        if self._preview_cap:
            self._preview_cap.release()
            self._preview_cap = None

        if self.state == self.STATE_PREVIEWING:
            self.state = self.STATE_FINISHED
            self.preview_btn.setText("▶ Preview Video")
            self.preview_btn.setStyleSheet("background-color: #388e3c; color: white; padding: 6px 14px; font-weight: bold; border-radius: 4px;")
            self.status_label.setText(f"Preview stopped. Clip saved: {os.path.basename(self.recorded_video_path)}")

    def _position_overlays(self):
        w = self.video_container.width()
        h = self.video_container.height()

        # Center countdown overlay
        cw = self.countdown_overlay.width()
        ch = self.countdown_overlay.height()
        self.countdown_overlay.move((w - cw) // 2, (h - ch) // 2)
        self.countdown_overlay.raise_()

        # Top-left recording badge
        self.rec_badge.move(14, 14)
        self.rec_badge.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlays()

    def request_annotation(self):
        if self.recorded_video_path and os.path.exists(self.recorded_video_path):
            self.annotate_requested.emit(
                self.recorded_video_path,
                self.recorded_frame_count,
                self.recorded_duration,
            )
            self.close()

    def closeEvent(self, event):
        self.countdown_timer.stop()
        self.stop_preview_playback()
        if self.camera_thread and self.camera_thread.is_recording:
            self.camera_thread.stop_recording()
        self.stop_camera()
        event.accept()
