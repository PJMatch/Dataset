from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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
        self.host_input.setText("172.20.18.209")
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
        self.setWindowTitle("Filter by Sentence ID")
        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel("Filter files by Sentence ID.\nLeave blank to load all files.")
        )

        row = QHBoxLayout()
        self.min_input = QLineEdit()
        self.min_input.setPlaceholderText("Min ID")
        row.addWidget(QLabel("From:"))
        row.addWidget(self.min_input)

        self.max_input = QLineEdit()
        self.max_input.setPlaceholderText("Max ID")
        row.addWidget(QLabel("To:"))
        row.addWidget(self.max_input)

        layout.addLayout(row)

        self.btn = QPushButton("Continue")
        self.btn.clicked.connect(self.accept)
        layout.addWidget(self.btn)

    def get_range(self):
        min_val = self.min_input.text().strip()
        max_val = self.max_input.text().strip()

        min_id = int(min_val) if min_val.isdigit() else None
        max_id = int(max_val) if max_val.isdigit() else None

        return min_id, max_id


class FileBrowserDialog(QDialog):
    def __init__(self, datasets, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Video")
        self.resize(400, 500)
        self.datasets = datasets
        self.selected_dataset = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Found {len(datasets)} files matching criteria:"))

        self.list_widget = QListWidget()
        for ds in datasets:
            prefix = "[✓] " if ds["annotated"] else "[  ] "
            self.list_widget.addItem(prefix + ds["name"])

        self.list_widget.itemDoubleClicked.connect(self.select_item)
        layout.addWidget(self.list_widget)

        self.load_btn = QPushButton("Load Selected")
        self.load_btn.clicked.connect(self.select_item)
        layout.addWidget(self.load_btn)

    def select_item(self):
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            self.selected_dataset = self.datasets[current_row]
            self.accept()
