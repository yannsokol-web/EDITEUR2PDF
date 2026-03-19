"""
Fenêtre de progression pour l'installation EditeurPDF.
Lit un fichier de progression écrit par installer.bat.
Format du fichier : "pourcentage;message"
  -1 = erreur, 100 = terminé
"""
import sys, os

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QPixmap, QIcon, QFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, 'logoediteurpdf.ico')
PROGRESS_FILE = sys.argv[1] if len(sys.argv) > 1 else ''

STYLE_BLUE = """
    QProgressBar { border: 1px solid #d9d9d9; border-radius: 9px; background-color: #ffffff; }
    QProgressBar::chunk { background-color: #1677ff; border-radius: 8px; }
"""
STYLE_GREEN = """
    QProgressBar { border: 1px solid #d9d9d9; border-radius: 9px; background-color: #ffffff; }
    QProgressBar::chunk { background-color: #52c41a; border-radius: 8px; }
"""
STYLE_RED = """
    QProgressBar { border: 1px solid #d9d9d9; border-radius: 9px; background-color: #ffffff; }
    QProgressBar::chunk { background-color: #ff4d4f; border-radius: 8px; }
"""


class ProgressWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Installation — EditeurPDF")
        self.setFixedSize(480, 340)
        self.setStyleSheet("background-color: #f0f2f5;")
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)
        layout.setContentsMargins(40, 30, 40, 30)

        # Logo
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        if os.path.exists(ICON_PATH):
            pix = QPixmap(ICON_PATH).scaled(QSize(96, 96), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pix)
        layout.addWidget(logo_label)

        # Titre
        title = QLabel("EditeurPDF")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        title.setStyleSheet("color: #1f1f1f;")
        layout.addWidget(title)

        # Statut
        self.status_label = QLabel("Préparation...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Segoe UI", 10))
        self.status_label.setStyleSheet("color: #595959;")
        layout.addWidget(self.status_label)

        # Barre de progression
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setStyleSheet(STYLE_BLUE)
        layout.addWidget(self.progress_bar)

        # Bouton fermer
        self.close_btn = QPushButton("Fermer")
        self.close_btn.setFixedHeight(36)
        self.close_btn.setFont(QFont("Segoe UI", 10))
        self.close_btn.setStyleSheet("""
            QPushButton { background-color: #1677ff; color: white; border: none; border-radius: 6px; padding: 0 24px; }
            QPushButton:hover { background-color: #0958d9; }
        """)
        self.close_btn.clicked.connect(self.close)
        self.close_btn.hide()
        layout.addWidget(self.close_btn, alignment=Qt.AlignCenter)

        # Timer pour lire le fichier de progression
        self.timer = QTimer()
        self.timer.timeout.connect(self._poll)
        self.timer.start(300)

    def _poll(self):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                line = f.read().strip()
            if ';' not in line:
                return
            val_str, msg = line.split(';', 1)
            val = int(val_str)

            if val == -1:
                self.progress_bar.setStyleSheet(STYLE_RED)
                self.status_label.setText(msg)
                self.close_btn.show()
                self.timer.stop()
            elif val >= 100:
                self.progress_bar.setValue(100)
                self.progress_bar.setStyleSheet(STYLE_GREEN)
                self.status_label.setText(msg)
                self.close_btn.show()
                self.timer.stop()
            else:
                self.progress_bar.setValue(val)
                self.status_label.setText(msg)
        except Exception:
            pass


if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = ProgressWindow()
    w.show()
    sys.exit(app.exec())
