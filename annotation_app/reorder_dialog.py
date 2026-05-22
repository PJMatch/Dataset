import json
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QListWidget, 
                             QPushButton, QLabel, QAbstractItemView, QMessageBox)

class ReorderDialog(QDialog):
    def __init__(self, glosses, timestamps, json_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review and Reorder")
        self.resize(400, 500)
        
        self.timestamps = sorted(timestamps)
        self.json_data = json_data

        layout = QVBoxLayout(self)

        info = QLabel("<b>Annotation Complete!</b><br>"
                      "Drag and drop the items below to change their order.<br>"
                      "<i>Timestamps will remain in chronological order.</i>")
        layout.addWidget(info)

        # Drag and drop list
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.addItems(glosses)
        layout.addWidget(self.list_widget)

        self.preview_btn = QPushButton("Preview Output JSON")
        self.preview_btn.clicked.connect(self.show_preview)
        layout.addWidget(self.preview_btn)

        self.save_btn = QPushButton("Save and Finish")
        self.save_btn.clicked.connect(self.accept)
        self.save_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        layout.addWidget(self.save_btn)

    def show_preview(self):
        current_order = self.get_reordered_glosses()
        preview_data = dict(self.json_data)
        preview_data["glosses"] = [[g, t] for g, t in zip(current_order, self.timestamps)]
        
        msg = QMessageBox(self)
        msg.setWindowTitle("JSON Preview")
        msg.setText(f"<pre>{json.dumps(preview_data, indent=4, ensure_ascii=False)}</pre>")
        msg.exec()

    def get_reordered_glosses(self):
        return [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
