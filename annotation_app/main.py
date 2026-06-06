import atexit
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from gui import MainWindow
from remote_dialogs import LoginDialog
from ssh_client import SSHManager

if __name__ == "__main__":
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
