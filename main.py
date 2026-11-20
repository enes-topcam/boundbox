import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app import theme
from app.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Etiketleme")
    app.setStyle("Fusion")
    theme.apply(QSettings("etiketleme", "etiketleme").value("tema", "sistem"))
    theme.follow_system()
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
