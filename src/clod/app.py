import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from clod.ui.main_window import MainWindow
from clod.ui.skull import Splash, skull_icon
from clod.ui.theme import FONT_FAMILY, INK, PAPER


def main():
    app = QApplication(sys.argv)
    app.setDesktopFileName("clod")  # GNOME/Wayland matches this to clod.desktop for the dock icon
    app.setWindowIcon(skull_icon(PAPER, INK))
    app.setStyle("Fusion")  # plain style we can fully recolour (native adds greys)
    font = QFont(FONT_FAMILY, 12)
    font.setStyleHint(QFont.Monospace)
    app.setFont(font)
    window = MainWindow()  # starts loading the model in the background
    splash = Splash(window)  # shows the window itself once the model is loaded
    splash.show()
    sys.exit(app.exec())
