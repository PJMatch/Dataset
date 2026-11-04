import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class ReorderDialog(QDialog):
    def __init__(self, glosses, timestamps, json_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review and Reorder")
        self.resize(420, 520)

        self.timestamps = sorted(timestamps)
        self.json_data = json_data

        display_glosses = list(glosses)
        self.has_eor = False
        if display_glosses and display_glosses[-1] == "EoR":
            self.has_eor = True
            display_glosses.pop()

        layout = QVBoxLayout(self)

        info = QLabel(
            "<b>Annotation Complete!</b><br>"
            "Drag and drop the items below to change their order.<br>"
            "Select an item and click <b>Delete</b> (or press Del) to remove a gloss that wasn't signed.<br>"
            "<i>Timestamps will remain in chronological order.</i>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.addItems(display_glosses)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        self.delete_btn = QPushButton("➖ Delete Selected Gloss")
        self.delete_btn.setStyleSheet(
            "background-color: #d9534f; color: white; font-weight: bold; padding: 6px;"
        )
        self.delete_btn.clicked.connect(self.delete_selected)
        btn_row.addWidget(self.delete_btn)

        self.preview_btn = QPushButton("🔍 Preview Output JSON")
        self.preview_btn.setStyleSheet("padding: 6px;")
        self.preview_btn.clicked.connect(self.show_preview)
        btn_row.addWidget(self.preview_btn)
        layout.addLayout(btn_row)

        self.save_btn = QPushButton("💾 Save and Finish")
        self.save_btn.clicked.connect(self.accept)
        self.save_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; font-size: 14px; padding: 8px;"
        )
        layout.addWidget(self.save_btn)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            event.accept()
        else:
            super().keyPressEvent(event)

    def delete_selected(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= self.list_widget.count():
            return
        if self.list_widget.count() <= 1:
            QMessageBox.warning(
                self, "Cannot Delete", "You must keep at least one gloss."
            )
            return

        self.list_widget.takeItem(row)
        content_count = len(self.timestamps) - (1 if self.has_eor else 0)
        if 0 <= row < content_count:
            self.timestamps.pop(row)

    def show_preview(self):
        current_order = self.get_reordered_glosses()
        preview_data = dict(self.json_data)
        preview_data["glosses"] = [
            [g, t] for g, t in zip(current_order, self.timestamps)
        ]

        msg = QMessageBox(self)
        msg.setWindowTitle("JSON Preview")
        msg.setText(
            f"<pre>{json.dumps(preview_data, indent=4, ensure_ascii=False)}</pre>"
        )
        msg.exec()

    def get_reordered_glosses(self):
        reordered = [
            self.list_widget.item(i).text() for i in range(self.list_widget.count())
        ]
        if self.has_eor:
            reordered.append("EoR")
        return reordered

    def get_final_timestamps(self):
        return list(self.timestamps)
