import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from data_model import AnnotationData
from remote_dialogs import FileBrowserDialog, RangeInputDialog
from reorder_dialog import ReorderDialog
from video_backend import VideoBackend


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
    finished = pyqtSignal(str, object)
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
            self.finished.emit(temp_video, annotation_data)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self, ssh_manager):
        super().__init__()
        self.ssh_manager = ssh_manager
        self.setWindowTitle("Dataset Annotator (SSH)")
        self.resize(800, 700)
        self.setStyleSheet(
            "QMainWindow { background-color: #2E2E2E; } QLabel { color: white; }"
        )

        self.video_backend = VideoBackend()
        self.annotation_data = None
        self.is_updating_slider = False
        self.current_temp_video = None

        self.dataset_cache = {}
        self.current_dataset = None

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # top bar
        top_bar = QHBoxLayout()
        self.load_btn = QPushButton("Browse Remote Files")
        self.load_btn.setStyleSheet(
            "background-color: #444; color: white; padding: 5px;"
        )
        self.load_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.load_btn.clicked.connect(self.browse_remote)
        top_bar.addWidget(self.load_btn)

        self.status_label = QLabel("Connected. Please browse for a video.")
        top_bar.addWidget(self.status_label)
        layout.addLayout(top_bar)

        # video player
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        self.video_label.setMinimumSize(640, 360)
        layout.addWidget(self.video_label, stretch=1)

        # slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.valueChanged.connect(self.on_slider_changed)
        self.slider.setEnabled(False)
        layout.addWidget(self.slider)

        # combo box for current gloss
        gloss_layout = QHBoxLayout()
        self.gloss_label = QLabel("Current Gloss:")
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
        gloss_layout.addWidget(self.gloss_combo)

        gloss_layout.addStretch()
        layout.addLayout(gloss_layout)

        # history list and delete button
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

    def cleanup_temp_video(self):
        if self.video_backend.cap:
            self.video_backend.cap.release()
            self.video_backend.cap = None

        if self.current_temp_video and os.path.exists(self.current_temp_video):
            try:
                os.remove(self.current_temp_video)
            except Exception as e:
                print(f"Failed to delete temp video: {e}")
            self.current_temp_video = None

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

        self.load_btn.setEnabled(False)
        self.status_label.setText(
            "Fetching file list from server (this may take a moment)..."
        )

        self.fetch_worker = FetchListWorker(self.ssh_manager, min_id, max_id)
        self.fetch_worker.finished.connect(self.on_fetch_success)
        self.fetch_worker.error.connect(self.on_fetch_error)
        self.fetch_worker.start()

    def on_fetch_success(self, datasets, from_cache=False):
        if not from_cache:
            self.dataset_cache[self.last_query_key] = datasets

        self.load_btn.setEnabled(True)
        self.status_label.setText("Select a video from the list.")

        browser = FileBrowserDialog(datasets, self)
        if browser.exec() == QDialog.DialogCode.Accepted and browser.selected_dataset:
            self.current_dataset = browser.selected_dataset
            self.load_dataset(browser.selected_dataset)
        else:
            self.status_label.setText("Browse cancelled.")

    def on_fetch_error(self, err_msg):
        self.load_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to list datasets:\n{err_msg}")
        self.status_label.setText("Error fetching files.")

    def load_dataset(self, dataset):
        self.load_btn.setEnabled(False)
        self.status_label.setText(f"Downloading {dataset['name']} to temp memory...")

        self.cleanup_temp_video()

        self.download_worker = DownloadWorker(self.ssh_manager, dataset)
        self.download_worker.finished.connect(self.on_download_success)
        self.download_worker.error.connect(self.on_download_error)
        self.download_worker.start()

    def on_download_success(self, temp_video, annotation_data):
        self.load_btn.setEnabled(True)
        self.current_temp_video = temp_video
        self.video_backend.load(self.current_temp_video)
        self.annotation_data = annotation_data

        self.slider.setEnabled(True)
        self.slider.setMinimum(0)
        self.slider.setMaximum(self.video_backend.total_frames - 1)
        self.slider.setValue(0)

        self.gloss_combo.clear()
        self.gloss_combo.addItems(self.annotation_data.original_glosses)
        self.gloss_combo.setEnabled(True)

        self.update_ui_state()
        self.show_frame(0)

    def on_download_error(self, err_msg):
        self.load_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to load dataset:\n{err_msg}")
        self.status_label.setText("Error loading dataset.")

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

            self.status_label.setText(
                f"Frame: {frame_idx} / {self.video_backend.total_frames - 1}"
            )

    def on_slider_changed(self, value):
        if not self.is_updating_slider:
            self.show_frame(value)

    def step_frame(self, step):
        if self.video_backend.cap:
            new_idx = self.video_backend.current_frame_idx + step
            self.show_frame(new_idx)

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
            self.finish_annotation()

    def delete_selected_timestamp(self):
        """Deletes the highlighted item from the history list."""
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
        else:
            self.gloss_label.setText("Current Gloss:")
            self.gloss_combo.setEnabled(True)

        self.history_list.clear()
        for g, t in zip(
            self.annotation_data.recorded_glosses, self.annotation_data.timestamps
        ):
            self.history_list.addItem(f"{g} (Frame: {t})")

        if self.history_list.count() > 0:
            self.history_list.setCurrentRow(self.history_list.count() - 1)

    def finish_annotation(self):
        dialog = ReorderDialog(
            self.annotation_data.recorded_glosses,
            self.annotation_data.timestamps,
            self.annotation_data.data,
            self,
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            reordered = dialog.get_reordered_glosses()
            try:
                self.annotation_data.finalize_and_save(reordered)
                QMessageBox.information(
                    self, "Success", "JSON updated on remote server!"
                )

                if self.current_dataset:
                    self.current_dataset["annotated"] = True

            except Exception as e:
                QMessageBox.critical(self, "Save Error", str(e))

            self.cleanup_temp_video()
            self.annotation_data = None
            self.video_label.clear()
            self.slider.setEnabled(False)
            self.gloss_combo.clear()
            self.gloss_combo.setEnabled(False)
            self.history_list.clear()
            self.status_label.setText("Please browse for a new video.")

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

    def closeEvent(self, event):
        self.cleanup_temp_video()
        self.ssh_manager.disconnect()
        event.accept()
