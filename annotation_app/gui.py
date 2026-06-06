import csv
import json
import os

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from data_model import (
    MIN_SEGMENT_FRAMES,
    AnnotationData,
    clamp_insert_frame,
    clamp_stamp_frame,
)
from remote_dialogs import FileBrowserDialog, RangeInputDialog
from reorder_dialog import ReorderDialog
from video_backend import VideoBackend
from video_transport import VideoTransport


class FetchListWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, ssh_manager, min_id, max_id):
        super().__init__()
        self.ssh_manager = ssh_manager
        self.min_id = min_id
        self.max_id = max_id

    def run(self):
        try:
            datasets = self.ssh_manager.list_datasets(
                min_id=self.min_id, max_id=self.max_id
            )
            self.finished.emit(datasets)
        except Exception as e:
            self.error.emit(str(e))


class DownloadWorker(QThread):
    finished = pyqtSignal(str, object, bool)
    error = pyqtSignal(str)

    def __init__(self, ssh_manager, dataset):
        super().__init__()
        self.ssh_manager = ssh_manager
        self.dataset = dataset

    def run(self):
        try:
            temp_video = self.ssh_manager.download_video_temp(self.dataset["mp4_path"])
            annotation_data = AnnotationData(
                self.ssh_manager, self.dataset["json_path"]
            )
            is_writable = self.ssh_manager.check_writable(self.dataset["json_path"])
            self.finished.emit(temp_video, annotation_data, is_writable)
        except Exception as e:
            self.error.emit(str(e))


class ExchangeDialog(QDialog):
    def __init__(self, word_pool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Gloss")
        self.resize(300, 400)
        self.word_pool = word_pool
        self.selected_word = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Type to filter, then double-click a word:"))

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search...")
        self.search_box.textChanged.connect(self.filter_list)
        layout.addWidget(self.search_box)

        self.list_widget = QListWidget()
        self.list_widget.addItems(self.word_pool)
        self.list_widget.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.list_widget)

        self.btn = QPushButton("Select Highlighted")
        self.btn.setStyleSheet(
            "background-color: #5bc0de; color: black; font-weight: bold;"
        )
        self.btn.clicked.connect(self.accept_selection)
        layout.addWidget(self.btn)

    def filter_list(self, text):
        self.list_widget.clear()
        if not text:
            self.list_widget.addItems(self.word_pool)
        else:
            filtered = [w for w in self.word_pool if text.lower() in w.lower()]
            self.list_widget.addItems(filtered)

    def accept_selection(self):
        if self.list_widget.currentItem():
            self.selected_word = self.list_widget.currentItem().text()
            self.accept()


class EditStructureDialog(QDialog):
    def __init__(self, current_glosses, word_pool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit JSON Structure")
        self.resize(350, 500)
        self.word_pool = word_pool

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Drag and drop to reorder.\nUse buttons below to modify the list:")
        )

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        display_glosses = list(current_glosses)
        if display_glosses and display_glosses[-1] == "EoR":
            display_glosses.pop()

        self.list_widget.addItems(display_glosses)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("➕ Add")
        self.add_btn.clicked.connect(self.add_gloss)
        btn_row.addWidget(self.add_btn)

        self.remove_btn = QPushButton("➖ Remove")
        self.remove_btn.clicked.connect(self.remove_gloss)
        btn_row.addWidget(self.remove_btn)

        self.exchange_btn = QPushButton("🔄 Exchange")
        self.exchange_btn.clicked.connect(self.exchange_gloss)
        btn_row.addWidget(self.exchange_btn)

        layout.addLayout(btn_row)

        save_row = QHBoxLayout()
        self.save_btn = QPushButton("💾 Save New Structure")
        self.save_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; padding: 5px;"
        )
        self.save_btn.clicked.connect(self.accept)
        save_row.addStretch()
        save_row.addWidget(self.save_btn)
        layout.addLayout(save_row)

    def add_gloss(self):
        dialog = ExchangeDialog(self.word_pool, self)
        dialog.setWindowTitle("Select Gloss to Add")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_word:
            row = self.list_widget.currentRow()
            if row < 0:
                row = self.list_widget.count()
            else:
                row += 1
            self.list_widget.insertItem(row, dialog.selected_word)
            self.list_widget.setCurrentRow(row)

    def remove_gloss(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.list_widget.takeItem(row)

    def exchange_gloss(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            dialog = ExchangeDialog(self.word_pool, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_word:
                self.list_widget.item(row).setText(dialog.selected_word)

    def get_new_structure(self):
        glosses = [
            self.list_widget.item(i).text() for i in range(self.list_widget.count())
        ]
        glosses.append("EoR")
        return glosses


class MainWindow(QMainWindow):
    def __init__(self, ssh_manager):
        super().__init__()
        self.ssh_manager = ssh_manager
        self.setWindowTitle("Dataset Annotator (SSH)")
        self.resize(900, 700)
        self.setStyleSheet(
            "QMainWindow { background-color: #2E2E2E; } QLabel { color: white; }"
        )

        self.video_backend = VideoBackend()
        self.annotation_data = None
        self.is_updating_slider = False
        self.current_temp_video = None

        self.dataset_cache = {}
        self.current_dataset = None
        self.last_query_key = None
        self.current_is_writable = True

        self.word_pool = []
        self.load_word_pool()

        self._gloss_color_map = {}

        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._preview_tick)
        self._preview_end_frame = 0
        self._syncing_selection = False

        self.init_ui()

    def load_word_pool(self):
        if os.path.exists("word_pool.csv"):
            with open("word_pool.csv", "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row:
                        self.word_pool.append(row[0].strip())
        else:
            print("Warning: word_pool.csv not found in the application directory.")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        top_bar = QHBoxLayout()
        self.browse_btn = QPushButton("Fetch New Range")
        self.browse_btn.setStyleSheet(
            "background-color: #444; color: white; padding: 5px; font-weight: bold;"
        )
        self.browse_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.browse_btn.setFixedHeight(35)
        self.browse_btn.clicked.connect(self.browse_remote)
        top_bar.addWidget(self.browse_btn)

        self.cached_list_btn = QPushButton("Show Cached List")
        self.cached_list_btn.setStyleSheet(
            "background-color: #5bc0de; color: black; padding: 5px; font-weight: bold;"
        )
        self.cached_list_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cached_list_btn.setEnabled(False)
        self.cached_list_btn.setFixedHeight(35)
        self.cached_list_btn.clicked.connect(self.show_cached_list)
        top_bar.addWidget(self.cached_list_btn)

        self.status_label = QLabel("Connected. Please fetch a new range.")
        self.status_label.setTextFormat(Qt.TextFormat.RichText)
        top_bar.addWidget(self.status_label)

        self.reject_btn = QPushButton("🗑 Reject Video")
        self.reject_btn.setStyleSheet(
            "background-color: #d9534f; color: white; font-weight: bold; padding: 5px;"
        )
        self.reject_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reject_btn.setEnabled(False)
        self.reject_btn.setFixedHeight(35)
        self.reject_btn.clicked.connect(self.reject_video)
        top_bar.addWidget(self.reject_btn)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        self.video_container = QWidget()
        self.video_container.setMinimumSize(640, 360)
        self.video_container.setStyleSheet("background-color: black;")
        video_container_layout = QVBoxLayout(self.video_container)
        video_container_layout.setContentsMargins(0, 0, 0, 0)

        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        video_container_layout.addWidget(self.video_label)

        self.next_gloss_overlay = QLabel(self.video_container)
        self.next_gloss_overlay.setStyleSheet(
            "QLabel {"
            "  background: transparent;"
            "  color: rgba(255, 224, 130, 0.5);"
            "  font-size: 52px;"
            "  font-weight: bold;"
            "  padding: 0;"
            "}"
        )
        self.next_gloss_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.next_gloss_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.next_gloss_overlay.hide()

        layout.addWidget(self.video_container, stretch=1)

        self.slider = VideoTransport()
        self.slider.valueChanged.connect(self.on_slider_changed)
        self.slider.boundaryChanged.connect(self.on_boundary_changed)
        self.slider.glossOrderMoved.connect(self.on_gloss_order_moved)
        self.slider.segmentContextMenuRequested.connect(
            self.on_segment_context_menu
        )
        self.slider.stampSelectionChanged.connect(self.on_stamp_selection_changed)
        self.slider.setEnabled(False)
        layout.addWidget(self.slider)

        gloss_layout = QHBoxLayout()
        self.gloss_label = QLabel("Gloss:")
        self.gloss_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: white;"
        )
        gloss_layout.addWidget(self.gloss_label)

        self.gloss_combo = QComboBox()
        self.gloss_combo.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: white; background-color: #555;"
        )
        self.gloss_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.gloss_combo.setEnabled(False)
        self.gloss_combo.setFixedHeight(35)
        self.gloss_combo.currentIndexChanged.connect(
            lambda _: self.update_next_gloss_overlay()
        )
        gloss_layout.addWidget(self.gloss_combo)

        self.exchange_btn = QPushButton("🔄")
        self.exchange_btn.setToolTip("Exchange Current Word")
        self.exchange_btn.setStyleSheet(
            "background-color: #337ab7; color: white; font-size: 16px;"
        )
        self.exchange_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.exchange_btn.setEnabled(False)
        self.exchange_btn.setFixedSize(35, 35)
        self.exchange_btn.clicked.connect(self.quick_exchange_gloss)
        gloss_layout.addWidget(self.exchange_btn)

        gloss_layout.addStretch()

        self.save_btn = QPushButton("💾 Save Video")
        self.save_btn.setStyleSheet(
            "background-color: #5cb85c; color: white; font-weight: bold; padding: 5px;"
        )
        self.save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.save_btn.setEnabled(False)
        self.save_btn.setFixedHeight(35)
        self.save_btn.clicked.connect(self.manual_save)
        gloss_layout.addWidget(self.save_btn)

        self.tools_btn = QToolButton()
        self.tools_btn.setText("⚙")
        self.tools_btn.setToolTip("More actions")
        self.tools_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.tools_btn.setStyleSheet(
            "QToolButton {"
            "  background-color: #555;"
            "  color: white;"
            "  font-size: 18px;"
            "  font-weight: bold;"
            "  border: none;"
            "  border-radius: 4px;"
            "}"
            "QToolButton:disabled { background-color: #3a3a3a; color: #888; }"
            "QToolButton::menu-indicator { image: none; }"
        )
        self.tools_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tools_btn.setEnabled(False)
        self.tools_btn.setFixedSize(35, 35)
        self._tools_menu = QMenu(self)
        self._tools_menu.setStyleSheet(self._context_menu_style())
        self._action_edit_list = self._tools_menu.addAction("Edit List")
        self._action_do_later = self._tools_menu.addAction("Do Later")
        self._action_reset = self._tools_menu.addAction("Reset")
        self._action_preview_json = self._tools_menu.addAction("Preview JSON")
        self._action_edit_list.triggered.connect(self.edit_structure)
        self._action_do_later.triggered.connect(self.skip_video)
        self._action_reset.triggered.connect(self.reset_annotation_progress)
        self._action_preview_json.triggered.connect(self.preview_json)
        self.tools_btn.setMenu(self._tools_menu)
        gloss_layout.addWidget(self.tools_btn)

        layout.addLayout(gloss_layout)

        history_layout = QVBoxLayout()
        history_layout.addWidget(
            QLabel(
                "Recorded Timestamps (synced with timeline selection; Delete to remove)"
            )
        )

        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(120)
        self.history_list.setStyleSheet("background-color: #444; color: white;")
        self.history_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_list.currentRowChanged.connect(self.on_history_row_changed)
        history_layout.addWidget(self.history_list)

        self.delete_btn = QPushButton("Delete Selected Timestamp")
        self.delete_btn.setStyleSheet(
            "background-color: #d9534f; color: white; font-weight: bold; padding: 5px;"
        )
        self.delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.delete_btn.clicked.connect(self.delete_selected_timestamp)
        history_layout.addWidget(self.delete_btn)

        layout.addLayout(history_layout)

    def cleanup_temp_video(self):
        if self.video_backend.cap:
            self.video_backend.cap.release()
            self.video_backend.cap = None
        if self.current_temp_video and os.path.exists(self.current_temp_video):
            try:
                os.remove(self.current_temp_video)
            except Exception:
                pass
            self.current_temp_video = None

    def stop_gloss_preview(self):
        if self._preview_timer.isActive():
            self._preview_timer.stop()

    def _position_next_gloss_overlay(self):
        self.next_gloss_overlay.adjustSize()
        x = max(
            0,
            (self.video_container.width() - self.next_gloss_overlay.width()) // 2,
        )
        self.next_gloss_overlay.move(x, 6)
        self.next_gloss_overlay.raise_()

    def update_next_gloss_overlay(self):
        if not self.annotation_data or self.annotation_data.is_complete():
            self.next_gloss_overlay.hide()
            return
        word = self.gloss_combo.currentText()
        if word:
            self.next_gloss_overlay.setText(word)
            self._position_next_gloss_overlay()
            self.next_gloss_overlay.show()
        else:
            self.next_gloss_overlay.hide()

    def reset_annotation_ui(self):
        self._gloss_color_map = {}
        self.stop_gloss_preview()
        self.cleanup_temp_video()
        self.annotation_data = None
        self.video_label.clear()
        self.next_gloss_overlay.hide()
        self.slider.setEnabled(False)
        self.slider.set_gloss_colors({})
        self.slider.set_segments([])
        self.slider.clear_segment_selection()
        self.gloss_combo.clear()
        self.gloss_combo.setEnabled(False)
        self.exchange_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self._update_tools_menu_state()
        self.save_btn.setEnabled(False)
        self.history_list.clear()

    def set_buttons_enabled(self, state):
        self.browse_btn.setEnabled(state)
        if self.last_query_key in self.dataset_cache:
            self.cached_list_btn.setEnabled(state)

    def browse_remote(self):
        range_dialog = RangeInputDialog(self)
        if range_dialog.exec() == QDialog.DialogCode.Accepted:
            min_id, max_id = range_dialog.get_range()
        else:
            return

        self.last_query_key = (min_id, max_id)
        if self.last_query_key in self.dataset_cache:
            self.on_fetch_success(
                self.dataset_cache[self.last_query_key], from_cache=True
            )
            return

        self.set_buttons_enabled(False)
        self.status_label.setText(
            "Fetching file list from server (this may take a moment)..."
        )

        self.fetch_worker = FetchListWorker(self.ssh_manager, min_id, max_id)
        self.fetch_worker.finished.connect(self.on_fetch_success)
        self.fetch_worker.error.connect(self.on_fetch_error)
        self.fetch_worker.start()

    def show_cached_list(self):
        if self.last_query_key in self.dataset_cache:
            self.on_fetch_success(
                self.dataset_cache[self.last_query_key], from_cache=True
            )

    def on_fetch_success(self, datasets, from_cache=False):
        if not from_cache:
            self.dataset_cache[self.last_query_key] = datasets

        self.set_buttons_enabled(True)
        self.status_label.setText("Select a video from the list.")

        browser = FileBrowserDialog(datasets, self)
        if browser.exec() == QDialog.DialogCode.Accepted and browser.selected_dataset:
            self.current_dataset = browser.selected_dataset

            if self.last_query_key and self.last_query_key in self.dataset_cache:
                current_list = self.dataset_cache[self.last_query_key]
                if self.current_dataset in current_list:
                    idx = current_list.index(self.current_dataset)
                    rotated_list = current_list[idx:] + current_list[:idx]
                    self.dataset_cache[self.last_query_key] = rotated_list

            self.load_dataset(self.current_dataset)
        else:
            self.status_label.setText("Browse cancelled.")

    def on_fetch_error(self, err_msg):
        self.set_buttons_enabled(True)
        QMessageBox.critical(self, "Error", f"Failed to list datasets:\n{err_msg}")
        self.status_label.setText("Error fetching files.")

    def load_dataset(self, dataset):
        self.set_buttons_enabled(False)
        self.reset_annotation_ui()
        self.status_label.setText(f"Downloading {dataset['name']} to temp memory...")

        self.download_worker = DownloadWorker(self.ssh_manager, dataset)
        self.download_worker.finished.connect(self.on_download_success)
        self.download_worker.error.connect(self.on_download_error)
        self.download_worker.start()

    def on_download_success(self, temp_video, annotation_data, is_writable):
        self.set_buttons_enabled(True)
        self.current_is_writable = is_writable
        self.reject_btn.setEnabled(is_writable)
        self.save_btn.setEnabled(is_writable)

        if self.word_pool and is_writable:
            self.exchange_btn.setEnabled(True)
        self._update_tools_menu_state()

        self.current_temp_video = temp_video
        self.video_backend.load(self.current_temp_video)
        self.annotation_data = annotation_data
        self._assign_gloss_colors()

        self.slider.setEnabled(True)
        self.slider.setMinimum(0)
        self.slider.setMaximum(self.video_backend.total_frames - 1)
        self.slider.setValue(0)
        self.slider.set_total_frames(self.video_backend.total_frames)
        self._refresh_stamp_slider()

        self.gloss_combo.clear()
        self.gloss_combo.addItems(self.annotation_data.original_glosses)
        self.gloss_combo.setEnabled(True)

        self.update_ui_state()
        self.show_frame(0)

    def on_download_error(self, err_msg):
        self.set_buttons_enabled(True)
        QMessageBox.critical(self, "Error", f"Failed to load dataset:\n{err_msg}")
        self.status_label.setText("Error loading dataset.")

    def load_next_dataset(self):
        next_dataset = None

        if self.last_query_key and self.last_query_key in self.dataset_cache:
            current_list = self.dataset_cache[self.last_query_key]

            if self.current_dataset in current_list:
                idx = current_list.index(self.current_dataset)
                current_list = current_list[idx + 1 :] + current_list[: idx + 1]
                self.dataset_cache[self.last_query_key] = current_list

            for ds in current_list:
                if not ds["annotated"]:
                    next_dataset = ds
                    break

        if next_dataset:
            self.current_dataset = next_dataset
            self.load_dataset(next_dataset)
        else:
            self.status_label.setText(
                "Finished the current batch! Please fetch a new range."
            )
            QMessageBox.information(
                self, "Finished", "All videos in the current list are complete!"
            )

    def show_frame(self, frame_idx):
        frame = self.video_backend.get_frame(frame_idx)
        if frame is not None:
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)

            self.video_label.setPixmap(
                pixmap.scaled(
                    self.video_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.is_updating_slider = True
            self.slider.setValue(frame_idx)
            self.is_updating_slider = False
            self._refresh_stamp_slider()

            if self.next_gloss_overlay.isVisible():
                self._position_next_gloss_overlay()

            if self.current_dataset:
                dot = "🟢" if self.current_is_writable else "🔴"
                color = "#4CAF50" if self.current_is_writable else "#F44336"
                fname = f"{self.current_dataset['name']}.json"
                text = f"Frame: {frame_idx} / {self.video_backend.total_frames - 1}   |   {dot} <span style='color:{color}; font-weight:bold;'>{fname}</span>"
            else:
                text = f"Frame: {frame_idx} / {self.video_backend.total_frames - 1}"

            self.status_label.setText(text)

    def _assign_gloss_colors(self):
        """Assign one of 16 palette indices per gloss name when the video loads."""
        self._gloss_color_map = {}
        if not self.annotation_data:
            return
        next_idx = 0
        for gloss in self.annotation_data.original_glosses:
            if gloss == "EoR":
                continue
            if gloss not in self._gloss_color_map:
                self._gloss_color_map[gloss] = next_idx % 16
                next_idx += 1

    def _ensure_gloss_color(self, gloss):
        if not gloss or gloss == "EoR":
            return
        if gloss not in self._gloss_color_map:
            self._gloss_color_map[gloss] = len(self._gloss_color_map) % 16

    def _build_stamp_segments(self):
        if not self.annotation_data:
            return []
        glosses = self.annotation_data.recorded_glosses
        times = self.annotation_data.timestamps
        playhead = self.video_backend.current_frame_idx
        max_frame = self.video_backend.total_frames - 1
        segments = []

        if not times:
            return []

        for i, (gloss, start) in enumerate(zip(glosses, times)):
            if gloss == "EoR":
                continue
            if i + 1 < len(times):
                end = times[i + 1]
            else:
                end = playhead
            end = max(end, start + MIN_SEGMENT_FRAMES)
            end = min(end, max_frame)
            if end <= start:
                end = min(max_frame, start + MIN_SEGMENT_FRAMES)
            segments.append((gloss, start, end, i, False))

        return segments

    def _pending_original_indices(self):
        if not self.annotation_data:
            return []
        original = self.annotation_data.original_glosses
        recorded_n = len(self.annotation_data.recorded_glosses)
        eor_i = self._eor_original_index()
        return [
            i
            for i in range(recorded_n, eor_i if eor_i >= 0 else len(original))
            if original[i] != "EoR"
        ]

    def _planned_timeline_range(self, max_frame):
        playhead = self.video_backend.current_frame_idx
        range_start = min(max_frame, playhead)
        if self.annotation_data and self.annotation_data.timestamps:
            after_last = min(
                max_frame,
                max(self.annotation_data.timestamps) + MIN_SEGMENT_FRAMES,
            )
            range_start = max(range_start, after_last)
        return range_start, max_frame

    def _build_planned_segments(self):
        if not self.annotation_data:
            return []
        original = self.annotation_data.original_glosses
        max_frame = self.video_backend.total_frames - 1
        pending = self._pending_original_indices()
        if not pending:
            return []

        range_start, range_end = self._planned_timeline_range(max_frame)
        if range_start > range_end:
            return []

        slot_count = len(pending)
        span = range_end - range_start + 1
        slot_width = max(1, span // slot_count)

        segments = []
        for slot_i, orig_i in enumerate(pending):
            start = range_start + slot_i * slot_width
            if slot_i == slot_count - 1:
                end = range_end
            else:
                end = range_start + (slot_i + 1) * slot_width - 1
            if start > range_end:
                break
            segments.append((original[orig_i], start, end, orig_i, True))
        return segments

    def _eor_original_index(self):
        if not self.annotation_data:
            return -1
        return self.annotation_data._eor_original_index()

    def _refresh_stamp_slider(self):
        if not isinstance(self.slider, VideoTransport):
            return
        if self.video_backend.cap:
            if self.annotation_data:
                self.annotation_data.repair_timestamps(
                    self.video_backend.total_frames - 1
                )
                eor_i = self.annotation_data.eor_index()
                self.slider.set_eor_stamp_index(
                    eor_i if eor_i is not None else -1
                )
            else:
                self.slider.set_eor_stamp_index(-1)
            self.slider.set_total_frames(self.video_backend.total_frames)
            self.slider.set_gloss_colors(self._gloss_color_map)
            planned = self._build_planned_segments()
            recorded = self._build_stamp_segments()
            self.slider.set_segments(planned + recorded)
            if self.annotation_data:
                recorded_n = len(self.annotation_data.recorded_glosses)
                eor_orig = self._eor_original_index()
                last_movable = eor_orig - 1 if eor_orig > 0 else -1
                self.slider.set_planned_move_range(recorded_n, last_movable)
                self.slider.set_boundaries(self.annotation_data.timestamps)
            else:
                self.slider.set_boundaries([])
        else:
            self.slider.set_gloss_colors({})
            self.slider.set_segments([])
            self.slider.set_boundaries([])

    def on_boundary_changed(self, index, frame):
        if not self.annotation_data:
            return
        times = self.annotation_data.timestamps
        if index < 0 or index >= len(times):
            return
        max_frame = self.video_backend.total_frames - 1
        times[index] = clamp_stamp_frame(times, index, frame, max_frame)
        self._refresh_stamp_slider()
        self.update_ui_state()
        self.show_frame(frame)

    def _segment_frame_range(self, segment_index):
        if not self.annotation_data:
            return None
        glosses = self.annotation_data.recorded_glosses
        times = self.annotation_data.timestamps
        if segment_index < 0 or segment_index >= len(times):
            return None
        if glosses[segment_index] == "EoR":
            return None
        start = times[segment_index]
        if segment_index + 1 < len(times):
            end = times[segment_index + 1] - 1
        else:
            end = self.video_backend.current_frame_idx
        end = max(start, min(end, self.video_backend.total_frames - 1))
        return start, end

    def _preview_interval_ms(self):
        fps = self.video_backend.fps or 25.0
        return max(1, int(1000 / fps))

    def start_gloss_preview(self, segment_index):
        if not self.video_backend.cap:
            return
        span = self._segment_frame_range(segment_index)
        if not span:
            return
        start, end = span
        if end < start:
            return
        self.stop_gloss_preview()
        self._preview_end_frame = end
        self.show_frame(start)
        self._preview_timer.start(self._preview_interval_ms())

    def _preview_tick(self):
        idx = self.video_backend.current_frame_idx
        if idx >= self._preview_end_frame:
            self.stop_gloss_preview()
            return
        self.show_frame(idx + 1)

    def on_gloss_order_moved(self, from_index, to_index):
        if not self.annotation_data:
            return
        self.annotation_data.move_gloss_in_order(from_index, to_index)
        self._sync_gloss_combo()
        self._refresh_stamp_slider()
        self.update_ui_state()

    def _sync_gloss_combo(self):
        if not self.annotation_data:
            return
        next_idx = len(self.annotation_data.recorded_glosses)
        self.gloss_combo.blockSignals(True)
        self.gloss_combo.clear()
        self.gloss_combo.addItems(self.annotation_data.original_glosses)
        if next_idx < self.gloss_combo.count():
            self.gloss_combo.setCurrentIndex(next_idx)
        self.gloss_combo.blockSignals(False)
        self.update_next_gloss_overlay()

    def _update_tools_menu_state(self):
        has_data = self.annotation_data is not None
        writable = self.current_is_writable
        self.tools_btn.setEnabled(has_data)
        self._action_do_later.setEnabled(has_data)
        self._action_preview_json.setEnabled(has_data)
        self._action_edit_list.setEnabled(
            has_data and writable and bool(self.word_pool)
        )
        self._action_reset.setEnabled(has_data and writable)

    def preview_json(self):
        if not self.annotation_data:
            return

        preview_data = dict(self.annotation_data.data)
        if (
            self.annotation_data.recorded_glosses
            and self.annotation_data.timestamps
        ):
            preview_data["glosses"] = [
                [g, t]
                for g, t in zip(
                    self.annotation_data.recorded_glosses,
                    self.annotation_data.timestamps,
                )
            ]
        else:
            preview_data["glosses"] = list(self.annotation_data.original_glosses)

        msg = QMessageBox(self)
        msg.setWindowTitle("JSON Preview")
        msg.setText(
            f"<pre>{json.dumps(preview_data, indent=4, ensure_ascii=False)}</pre>"
        )
        msg.exec()
        self.setFocus()

    def _context_menu_style(self):
        return """
            QMenu {
                background-color: #323232;
                color: #f0f0f0;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
                padding: 6px 4px;
            }
            QMenu::item {
                padding: 8px 28px 8px 20px;
                border-radius: 4px;
                margin: 2px 6px;
            }
            QMenu::item:selected {
                background-color: #4a4a4a;
            }
            QMenu::separator {
                height: 1px;
                background: #4a4a4a;
                margin: 4px 10px;
            }
        """

    def on_segment_context_menu(
        self, segment_index, is_planned, frame, global_pos
    ):
        if not self.annotation_data:
            return

        menu = QMenu(self)
        menu.setStyleSheet(self._context_menu_style())

        if is_planned:
            selected = self.slider.selected_planned_index()
            is_selected_target = (
                selected is not None
                and segment_index >= 0
                and segment_index == selected
            )
            if is_selected_target:
                delete_action = menu.addAction("Delete gloss")
                replace_action = menu.addAction("Replace")
                if not self.current_is_writable:
                    delete_action.setEnabled(False)
                    replace_action.setEnabled(False)
                chosen = menu.exec(global_pos)
                if chosen is None:
                    return
                if chosen == delete_action:
                    self._delete_planned_gloss(segment_index)
                elif chosen == replace_action:
                    self._replace_planned_gloss(segment_index)
            else:
                add_action = menu.addAction("Add gloss")
                if not self.current_is_writable:
                    add_action.setEnabled(False)
                chosen = menu.exec(global_pos)
                if chosen is None:
                    return
                if chosen == add_action:
                    self._add_planned_gloss(segment_index)
            return

        selected = self.slider.selected_segment()
        is_selected_target = (
            selected is not None
            and segment_index >= 0
            and segment_index == selected
        )

        if is_selected_target:
            delete_action = menu.addAction("Delete gloss")
            replace_action = menu.addAction("Replace")
            preview_action = menu.addAction("Preview")
            if not self.current_is_writable:
                delete_action.setEnabled(False)
                replace_action.setEnabled(False)
            chosen = menu.exec(global_pos)
            if chosen is None:
                return
            if chosen == delete_action:
                self._delete_gloss_at_segment(segment_index)
            elif chosen == replace_action:
                self._replace_gloss_at_segment(segment_index)
            elif chosen == preview_action:
                self.setFocus()
                self.start_gloss_preview(segment_index)
        else:
            add_action = menu.addAction("Add gloss")
            if not self.current_is_writable:
                add_action.setEnabled(False)
            chosen = menu.exec(global_pos)
            if chosen is None:
                return
            if chosen == add_action:
                self._add_gloss(segment_index, frame)

    def _insert_index_for_frame(self, frame):
        times = self.annotation_data.timestamps
        for i, t in enumerate(times):
            if frame < t:
                return i
        return len(times)

    def _add_planned_gloss(self, original_index):
        if not self.annotation_data or not self.word_pool:
            return
        dialog = ExchangeDialog(self.word_pool, self)
        dialog.setWindowTitle("Add gloss")
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_word:
            return
        insert_at = (
            original_index + 1
            if original_index >= 0
            else len(self.annotation_data.recorded_glosses)
        )
        self.annotation_data.insert_original_gloss(insert_at, dialog.selected_word)
        self._ensure_gloss_color(dialog.selected_word)
        self._sync_gloss_combo()
        self._refresh_stamp_slider()
        self.update_ui_state()
        self.setFocus()

    def _delete_planned_gloss(self, original_index):
        if not self.annotation_data:
            return
        self.annotation_data.delete_original_gloss(original_index)
        self.slider.clear_segment_selection()
        self._sync_gloss_combo()
        self._refresh_stamp_slider()
        self.update_ui_state()

    def _replace_planned_gloss(self, original_index):
        if not self.annotation_data or not self.word_pool:
            return
        dialog = ExchangeDialog(self.word_pool, self)
        dialog.setWindowTitle("Replace gloss")
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_word:
            return
        self.annotation_data.replace_original_gloss(
            original_index, dialog.selected_word
        )
        self._ensure_gloss_color(dialog.selected_word)
        self._sync_gloss_combo()
        self._refresh_stamp_slider()
        self.update_ui_state()
        self.setFocus()

    def _add_gloss(self, segment_index, frame):
        if not self.annotation_data or not self.word_pool:
            return

        dialog = ExchangeDialog(self.word_pool, self)
        dialog.setWindowTitle("Add gloss")
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_word:
            return

        times = self.annotation_data.timestamps
        max_frame = self.video_backend.total_frames - 1

        if segment_index >= 0 and segment_index < len(times):
            insert_at = segment_index + 1
        else:
            insert_at = self._insert_index_for_frame(frame)

        eor_i = self.annotation_data.eor_index()
        if eor_i is not None:
            insert_at = min(insert_at, eor_i)

        clamped = clamp_insert_frame(times, insert_at, frame, max_frame)
        if clamped is None:
            QMessageBox.warning(
                self,
                "Cannot add gloss",
                "Not enough space between stamps for a visible segment.",
            )
            return
        frame = clamped

        self.annotation_data.insert_timestamp(
            insert_at, dialog.selected_word, frame
        )
        self._ensure_gloss_color(dialog.selected_word)
        self._refresh_stamp_slider()
        self.update_ui_state()
        self.show_frame(frame)

    def _replace_gloss_at_segment(self, segment_index):
        if not self.annotation_data or not self.word_pool:
            return
        if segment_index < 0 or segment_index >= len(
            self.annotation_data.recorded_glosses
        ):
            return
        if self.annotation_data.recorded_glosses[segment_index] == "EoR":
            return

        dialog = ExchangeDialog(self.word_pool, self)
        dialog.setWindowTitle("Replace gloss")
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_word:
            return

        self.annotation_data.recorded_glosses[segment_index] = dialog.selected_word
        self._ensure_gloss_color(dialog.selected_word)
        self._refresh_stamp_slider()
        self.update_ui_state()
        self.setFocus()

    def _delete_gloss_at_segment(self, segment_index):
        if not self.annotation_data:
            return
        if segment_index < 0 or segment_index >= len(
            self.annotation_data.timestamps
        ):
            return
        if self.annotation_data.recorded_glosses[segment_index] == "EoR":
            return

        deleted_gloss = self.annotation_data.recorded_glosses[segment_index]
        self.annotation_data.delete_timestamp(segment_index)

        idx = self.gloss_combo.findText(deleted_gloss)
        if idx >= 0:
            self.gloss_combo.setCurrentIndex(idx)

        self.slider.clear_segment_selection()
        self._refresh_stamp_slider()
        self.update_ui_state()

    def on_slider_changed(self, value):
        if not self.is_updating_slider:
            self.show_frame(value)

    def step_frame(self, step):
        self.stop_gloss_preview()
        if self.video_backend.cap:
            new_idx = self.video_backend.current_frame_idx + step
            self.show_frame(new_idx)

    def quick_exchange_gloss(self):
        if not self.annotation_data:
            return

        dialog = ExchangeDialog(self.word_pool, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_word:
            new_word = dialog.selected_word
            current_idx = self.gloss_combo.currentIndex()

            self.gloss_combo.setItemText(current_idx, new_word)
            self.annotation_data.original_glosses[current_idx] = new_word
            self._ensure_gloss_color(new_word)

        self.setFocus()

    def reset_annotation_progress(self):
        if not self.annotation_data or not self.current_is_writable:
            return

        reply = QMessageBox.question(
            self,
            "Reset annotation",
            "Restore the original gloss list from when this video was opened "
            "and delete all recorded stamps?\n\n"
            "Timeline edits (swap, replace, add) will also be undone. "
            "Nothing is saved to the server until you save the video.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.stop_gloss_preview()
        self.annotation_data.reset_to_factory()
        self.gloss_combo.clear()
        self.gloss_combo.addItems(self.annotation_data.original_glosses)
        self.gloss_combo.setCurrentIndex(0)
        self.gloss_combo.setEnabled(True)
        self.slider.clear_segment_selection()
        self.update_ui_state()
        self.setFocus()

    def edit_structure(self):
        """Opens the full list editor and resets progress if changed."""
        if not self.annotation_data:
            return

        if len(self.annotation_data.recorded_glosses) > 0:
            reply = QMessageBox.question(
                self,
                "Warning",
                "Editing the JSON structure will RESET your current recorded timestamps for this video.\n\nDo you want to proceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        dialog = EditStructureDialog(
            self.annotation_data.original_glosses, self.word_pool, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_struct = dialog.get_new_structure()
            try:
                self.annotation_data.update_structure(new_struct)

                self.gloss_combo.clear()
                self.gloss_combo.addItems(self.annotation_data.original_glosses)
                self.update_ui_state()
                QMessageBox.information(
                    self, "Success", "Structure updated and saved to server!"
                )

            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to save new structure:\n{e}"
                )

        self.setFocus()

    def validate_save_conditions(self):
        if not self.annotation_data:
            return False, "No data loaded."

        recorded = self.annotation_data.recorded_glosses
        if len(recorded) < 2:
            return False, "You must record at least 2 glosses to save."
        if recorded[-1] != "EoR":
            return (
                False,
                "The very last gloss recorded must be 'EoR' (End of Recording).",
            )

        return True, ""

    def manual_save(self):
        valid, msg = self.validate_save_conditions()
        if valid:
            self.finish_annotation()
        else:
            QMessageBox.warning(self, "Cannot Save", msg)

    def record_timestamp(self):
        if not self.annotation_data or self.annotation_data.is_complete():
            return
        current_frame = self.video_backend.current_frame_idx
        selected_gloss = self.gloss_combo.currentText()

        max_frame = self.video_backend.total_frames - 1
        self.annotation_data.add_timestamp(
            selected_gloss, current_frame, max_frame
        )

        next_index = self.gloss_combo.currentIndex() + 1
        if next_index < self.gloss_combo.count():
            self.gloss_combo.setCurrentIndex(next_index)

        self.update_ui_state()
        if self.history_list.count() > 0:
            self._syncing_selection = True
            self.history_list.setCurrentRow(self.history_list.count() - 1)
            self._syncing_selection = False

        if self.annotation_data.is_complete():
            valid, msg = self.validate_save_conditions()
            if valid:
                self.finish_annotation()
            else:
                QMessageBox.warning(
                    self,
                    "Cannot Auto-Save",
                    f"All glosses recorded, but cannot save yet:\n\n{msg}\n\nPlease fix your history list (Delete) to proceed.",
                )

    def _selected_stamp_index(self):
        stamp_idx = self.slider.selected_segment()
        if stamp_idx is not None:
            return stamp_idx
        row = self.history_list.currentRow()
        return row if row >= 0 else None

    def on_stamp_selection_changed(self, stamp_idx):
        if self._syncing_selection:
            return
        self._syncing_selection = True
        if stamp_idx < 0:
            self.history_list.clearSelection()
        elif stamp_idx < self.history_list.count():
            self.history_list.setCurrentRow(stamp_idx)
        self._syncing_selection = False

    def on_history_row_changed(self, row):
        if self._syncing_selection or not self.annotation_data:
            return
        if row < 0 or row >= len(self.annotation_data.timestamps):
            return
        self._syncing_selection = True
        self.slider.set_selected_segment(row)
        self._syncing_selection = False

    def delete_selected_timestamp(self):
        if not self.annotation_data:
            return
        stamp_idx = self._selected_stamp_index()
        if stamp_idx is None:
            return
        if self.annotation_data.recorded_glosses[stamp_idx] == "EoR":
            return

        deleted_gloss = self.annotation_data.recorded_glosses[stamp_idx]
        self.annotation_data.delete_timestamp(stamp_idx)

        idx = self.gloss_combo.findText(deleted_gloss)
        if idx >= 0:
            self.gloss_combo.setCurrentIndex(idx)

        self.slider.clear_segment_selection()
        self._syncing_selection = True
        self.history_list.clearSelection()
        self._syncing_selection = False
        self.update_ui_state()

    def update_ui_state(self):
        if not self.annotation_data:
            return

        if self.annotation_data.is_complete():
            self.gloss_label.setText("All glosses recorded! Save dialog opening...")
            self.gloss_combo.setEnabled(False)
            self.exchange_btn.setEnabled(False)
        else:
            self.gloss_label.setText("Gloss:")
            self.gloss_combo.setEnabled(True)
            if self.word_pool and self.current_is_writable:
                self.exchange_btn.setEnabled(True)

        stamp_sel = self.slider.selected_segment()
        self.history_list.clear()
        for g, t in zip(
            self.annotation_data.recorded_glosses, self.annotation_data.timestamps
        ):
            self.history_list.addItem(f"{g} (Frame: {t})")

        if (
            stamp_sel is not None
            and 0 <= stamp_sel < self.history_list.count()
        ):
            self._syncing_selection = True
            self.history_list.setCurrentRow(stamp_sel)
            self._syncing_selection = False

        self._refresh_stamp_slider()
        self._update_tools_menu_state()
        self.update_next_gloss_overlay()

    def reject_video(self):
        if not self.annotation_data or not self.current_dataset:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Rejection",
            "Are you SURE you want to mark this video as poorly recorded?\n\nThis will instantly set 'recorded_correctly: false' on the server and skip the video permanently.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.annotation_data.set_recorded_correctly_false()
                if self.current_dataset:
                    self.current_dataset["annotated"] = True

                self.reset_annotation_ui()
                self.load_next_dataset()

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to reject file:\n{e}")

    def skip_video(self):
        if not self.current_dataset or not self.last_query_key:
            return
        self.reset_annotation_ui()
        self.load_next_dataset()

    def finish_annotation(self):
        dialog = ReorderDialog(
            self.annotation_data.recorded_glosses,
            self.annotation_data.timestamps,
            self.annotation_data.data,
            self,
        )

        if not self.current_is_writable:
            dialog.save_btn.setEnabled(False)
            dialog.save_btn.setText("Cannot Save (Read-Only File)")
            dialog.save_btn.setStyleSheet(
                "background-color: #888; color: #ccc; font-weight: bold;"
            )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            reordered = dialog.get_reordered_glosses()
            try:
                self.annotation_data.finalize_and_save(reordered)
                if self.current_dataset:
                    self.current_dataset["annotated"] = True

                self.reset_annotation_ui()
                self.load_next_dataset()

            except Exception as e:
                QMessageBox.critical(self, "Save Error", str(e))

    def keyPressEvent(self, event):
        if not self.annotation_data:
            return super().keyPressEvent(event)

        if event.key() == Qt.Key.Key_Space:
            if self._preview_timer.isActive():
                self.stop_gloss_preview()
                event.accept()
                return
            seg = self.slider.selected_segment()
            if seg is not None:
                self.start_gloss_preview(seg)
                event.accept()
                return
        elif event.key() == Qt.Key.Key_Left:
            self.step_frame(-1)
        elif event.key() == Qt.Key.Key_Right:
            self.step_frame(1)
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.record_timestamp()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected_timestamp()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.next_gloss_overlay.isVisible():
            self._position_next_gloss_overlay()

    def closeEvent(self, event):
        self.stop_gloss_preview()
        self.cleanup_temp_video()
        self.ssh_manager.disconnect()
        event.accept()
