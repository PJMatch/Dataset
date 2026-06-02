import csv
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
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
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from data_model import AnnotationData
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
        self.next_gloss_overlay.setText("")
        self.next_gloss_overlay.setStyleSheet(
            "QLabel {"
            "  background: transparent;"
            "  color: rgba(255, 224, 130, 0.45);"
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

        self.edit_struct_btn = QPushButton("📝 Edit List")
        self.edit_struct_btn.setStyleSheet(
            "background-color: #9c27b0; color: white; font-weight: bold; padding: 5px;"
        )
        self.edit_struct_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.edit_struct_btn.setEnabled(False)
        self.edit_struct_btn.setFixedHeight(35)
        self.edit_struct_btn.clicked.connect(self.edit_structure)
        gloss_layout.addWidget(self.edit_struct_btn)

        gloss_layout.addStretch()

        self.skip_btn = QPushButton("⏭ Do Later")
        self.skip_btn.setStyleSheet(
            "background-color: #f0ad4e; color: black; font-weight: bold; padding: 5px;"
        )
        self.skip_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.skip_btn.setEnabled(False)
        self.skip_btn.setFixedHeight(35)
        self.skip_btn.clicked.connect(self.skip_video)
        gloss_layout.addWidget(self.skip_btn)

        self.save_btn = QPushButton("💾 Save Video")
        self.save_btn.setStyleSheet(
            "background-color: #5cb85c; color: white; font-weight: bold; padding: 5px;"
        )
        self.save_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.save_btn.setEnabled(False)
        self.save_btn.setFixedHeight(35)
        self.save_btn.clicked.connect(self.manual_save)
        gloss_layout.addWidget(self.save_btn)

        layout.addLayout(gloss_layout)

        history_layout = QVBoxLayout()
        history_layout.addWidget(
            QLabel("Recorded Timestamps (Click to select, press Delete to remove):")
        )

        self.history_list = QListWidget()
        self.history_list.setMaximumHeight(120)
        self.history_list.setStyleSheet("background-color: #444; color: white;")
        self.history_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        history_layout.addWidget(self.history_list)

        self.delete_btn = QPushButton("Delete Selected Timestamp")
        self.delete_btn.setStyleSheet(
            "background-color: #d9534f; color: white; font-weight: bold; padding: 5px;"
        )
        self.delete_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.delete_btn.clicked.connect(self.delete_selected_timestamp)
        history_layout.addWidget(self.delete_btn)

        layout.addLayout(history_layout)

    def _position_next_gloss_overlay(self):
        self.next_gloss_overlay.adjustSize()
        x = max(0, (self.video_container.width() - self.next_gloss_overlay.width()) // 2)
        self.next_gloss_overlay.move(x, 4)
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

    def reset_annotation_ui(self):
        self.cleanup_temp_video()
        self.annotation_data = None
        self.video_label.clear()
        self.next_gloss_overlay.hide()
        self.slider.setEnabled(False)
        self.slider.set_segments([])
        self.gloss_combo.clear()
        self.gloss_combo.setEnabled(False)
        self.exchange_btn.setEnabled(False)
        self.edit_struct_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
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
        self.skip_btn.setEnabled(True)

        self.current_is_writable = is_writable
        self.reject_btn.setEnabled(is_writable)
        self.save_btn.setEnabled(is_writable)

        if self.word_pool and is_writable:
            self.exchange_btn.setEnabled(True)
            self.edit_struct_btn.setEnabled(True)

        self.current_temp_video = temp_video
        self.video_backend.load(self.current_temp_video)
        self.annotation_data = annotation_data

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
            if self.next_gloss_overlay.isVisible():
                self._position_next_gloss_overlay()

            self.is_updating_slider = True
            self.slider.setValue(frame_idx)
            self.is_updating_slider = False
            self._refresh_stamp_slider()
            self.update_next_gloss_overlay()

            if self.current_dataset:
                dot = "🟢" if self.current_is_writable else "🔴"
                color = "#4CAF50" if self.current_is_writable else "#F44336"
                fname = f"{self.current_dataset['name']}.json"
                text = f"Frame: {frame_idx} / {self.video_backend.total_frames - 1}   |   {dot} <span style='color:{color}; font-weight:bold;'>{fname}</span>"
            else:
                text = f"Frame: {frame_idx} / {self.video_backend.total_frames - 1}"

            self.status_label.setText(text)

    def _build_stamp_segments(self):
        if not self.annotation_data:
            return []
        glosses = self.annotation_data.recorded_glosses
        times = self.annotation_data.timestamps
        playhead = self.video_backend.current_frame_idx
        segments = []

        if not times:
            return []

        for i, (gloss, start) in enumerate(zip(glosses, times)):
            if i + 1 < len(times):
                end = times[i + 1]
            else:
                end = playhead
            if end > start:
                segments.append((gloss, start, end))

        return segments

    def _refresh_stamp_slider(self):
        if not isinstance(self.slider, VideoTransport):
            return
        if self.video_backend.cap:
            self.slider.set_total_frames(self.video_backend.total_frames)
            self.slider.set_segments(self._build_stamp_segments())
            if self.annotation_data:
                self.slider.set_boundaries(self.annotation_data.timestamps)
            else:
                self.slider.set_boundaries([])
        else:
            self.slider.set_segments([])
            self.slider.set_boundaries([])

    def on_boundary_changed(self, index, frame):
        if not self.annotation_data:
            return
        times = self.annotation_data.timestamps
        if index <= 0 or index >= len(times) - 1:
            return
        times[index] = frame
        self._refresh_stamp_slider()
        self.update_ui_state()
        self.show_frame(frame)

    def on_slider_changed(self, value):
        if not self.is_updating_slider:
            self.show_frame(value)

    def step_frame(self, step):
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

        self.annotation_data.add_timestamp(selected_gloss, current_frame)

        next_index = self.gloss_combo.currentIndex() + 1
        if next_index < self.gloss_combo.count():
            self.gloss_combo.setCurrentIndex(next_index)

        self.update_ui_state()

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

    def delete_selected_timestamp(self):
        if not self.annotation_data:
            return
        current_row = self.history_list.currentRow()
        if current_row >= 0:
            deleted_gloss = self.annotation_data.recorded_glosses[current_row]
            self.annotation_data.delete_timestamp(current_row)

            idx = self.gloss_combo.findText(deleted_gloss)
            if idx >= 0:
                self.gloss_combo.setCurrentIndex(idx)

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

        self.history_list.clear()
        for g, t in zip(
            self.annotation_data.recorded_glosses, self.annotation_data.timestamps
        ):
            self.history_list.addItem(f"{g} (Frame: {t})")

        if self.history_list.count() > 0:
            self.history_list.setCurrentRow(self.history_list.count() - 1)

        self.update_next_gloss_overlay()
        self._refresh_stamp_slider()

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

        if event.key() == Qt.Key.Key_Left:
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
        self.cleanup_temp_video()
        self.ssh_manager.disconnect()
        event.accept()
