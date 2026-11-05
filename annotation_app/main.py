import atexit
import sys

import pandas as pd
from PyQt6.QtWidgets import QApplication, QMessageBox

from gui import MainWindow
from remote_dialogs import LoginDialog
from ssh_client import SSHManager


def read_words():
    data = pd.read_excel("../Sentences/word_pool.xlsx")
    all_words = data.stack()

    all_words.to_csv("word_pool.csv", index=False, header=False)


if __name__ == "__main__":
    read_words()
    app = QApplication(sys.argv)

    login = LoginDialog()
    if login.exec() == LoginDialog.DialogCode.Accepted:
        host, user, pwd = login.get_credentials()

        ssh_manager = SSHManager()
        try:
            ssh_manager.connect(host, user, pwd)
        except Exception as e:
            QMessageBox.critical(None, "Connection Failed", str(e))
            sys.exit(1)

        window = MainWindow(ssh_manager)

        atexit.register(window.cleanup_temp_video)
        atexit.register(ssh_manager.disconnect)

        window.show()
        sys.exit(app.exec())
