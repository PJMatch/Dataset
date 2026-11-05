from PyQt6.QtCore import Qt
import re
from PyQt6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Login")
        self.setFixedSize(300, 200)

        layout = QVBoxLayout(self)

        self.host_input = QLineEdit()
        self.host_input.setText("172.20.3.204")
        self.host_input.setPlaceholderText("IP Address")
        layout.addWidget(QLabel("Host IP:"))
        layout.addWidget(self.host_input)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Username")
        layout.addWidget(QLabel("Username:"))
        layout.addWidget(self.user_input)

        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setPlaceholderText("Password")
        layout.addWidget(QLabel("Password:"))
        layout.addWidget(self.pass_input)

        self.login_btn = QPushButton("Connect")
        self.login_btn.clicked.connect(self.accept)
        layout.addWidget(self.login_btn)

    def get_credentials(self):
        return self.host_input.text(), self.user_input.text(), self.pass_input.text()


class RangeInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter by Sentence ID (Person 6)")
        self.resize(380, 240)
        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel(
                "Filter Person 6 files by Sentence ID range or enter a list of IDs.\nLeave blank to load all files."
            )
        )

        range_group = QGroupBox("Range (From / To)")
        row = QHBoxLayout(range_group)
        self.min_input = QLineEdit()
        self.min_input.setPlaceholderText("Min ID")
        row.addWidget(QLabel("From:"))
        row.addWidget(self.min_input)

        self.max_input = QLineEdit()
        self.max_input.setPlaceholderText("Max ID")
        row.addWidget(QLabel("To:"))
        row.addWidget(self.max_input)
        layout.addWidget(range_group)

        list_group = QGroupBox("Or Specific ID List (comma-separated)")
        list_layout = QVBoxLayout(list_group)
        self.id_list_input = QLineEdit()
        self.id_list_input.setPlaceholderText("e.g. 279, 285, 423, 455, 239")
        list_layout.addWidget(self.id_list_input)
        layout.addWidget(list_group)

        self.btn = QPushButton("Continue")
        self.btn.clicked.connect(self.accept)
        layout.addWidget(self.btn)

    def get_range(self):
        min_val = self.min_input.text().strip()
        max_val = self.max_input.text().strip()

        min_id = int(min_val) if min_val.isdigit() else None
        max_id = int(max_val) if max_val.isdigit() else None

        return min_id, max_id

    def get_id_list(self):
        text = self.id_list_input.text().strip()
        if not text:
            return []
        tokens = re.split(r"[,;\s]+", text)
        ids = []
        for t in tokens:
            t = t.strip()
            if t.isdigit():
                val = int(t)
                if val not in ids:
                    ids.append(val)
        return ids


class IdListInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter by Sentence ID List (Person 6)")
        self.resize(450, 160)
        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel(
                "Enter sentence IDs separated by commas:\n(e.g. 279, 285, 423, 455, 239)"
            )
        )

        self.id_list_input = QLineEdit()
        self.id_list_input.setPlaceholderText("279, 285, 423, 455, 239")
        layout.addWidget(self.id_list_input)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        self.btn = QPushButton("Continue")
        self.btn.setDefault(True)
        self.btn.clicked.connect(self._on_continue)
        btn_box.addWidget(self.btn)

        layout.addLayout(btn_box)

    def _on_continue(self):
        ids = self.get_ids()
        if not ids:
            QMessageBox.warning(
                self,
                "Invalid Input",
                "Please enter at least one valid numeric sentence ID (e.g. 279, 285).",
            )
            return
        self.accept()

    def get_ids(self):
        text = self.id_list_input.text().strip()
        if not text:
            return []
        tokens = re.split(r"[,;\s]+", text)
        ids = []
        for t in tokens:
            t = t.strip()
            if t.isdigit():
                val = int(t)
                if val not in ids:
                    ids.append(val)
        return ids


class FileBrowserDialog(QDialog):
    def __init__(self, datasets, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Video")
        self.resize(750, 520)
        self.datasets = datasets
        self.selected_dataset = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Found {len(datasets)} videos:"))

        self.list_widget = QListWidget()
        self.list_widget.setWordWrap(True)
        for ds in datasets:
            prefix = "[✓] " if ds.get("annotated") else "[  ] "
            display_text = ds.get("sentence") or ds.get("name", "")
            item = QListWidgetItem(prefix + display_text)
            item.setToolTip(
                f"File: {ds.get('name')}.mp4\nSentence ID: {ds.get('sentence_id')}"
            )
            self.list_widget.addItem(item)

        if datasets:
            self.list_widget.setCurrentRow(0)

        self.list_widget.itemDoubleClicked.connect(self.select_item)
        self.list_widget.itemActivated.connect(self.select_item)
        layout.addWidget(self.list_widget)

        self.load_btn = QPushButton("Load Selected")
        self.load_btn.clicked.connect(self.select_item)
        layout.addWidget(self.load_btn)

    def select_item(self):
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            self.selected_dataset = self.datasets[current_row]
            self.accept()
