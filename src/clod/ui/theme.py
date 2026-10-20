from PySide6.QtGui import QColor, QPalette

FONT_FAMILY = "Iosevka Nerd Font Mono"  # falls back to any monospace if missing
INK = QColor("#111111")
PAPER = QColor("#fafafa")


# The whole UI uses only two colours: fg (text, borders) and bg (background).
# Light theme = ink on paper, dark theme = paper on ink. Emphasis = invert.
# Borders only where they mean something: the prompt (where you write) and the
# three hairlines that split the window. Everything else is bare until hovered.
STYLE = """
* {{ background: {bg}; color: {fg}; placeholder-text-color: {fg}; font-family: "{font}", monospace; font-size: 12pt; }}
QToolBar {{ border: none; border-bottom: 1px solid {fg}; padding: 6px 10px; spacing: 6px; }}
QPushButton, QComboBox {{ border: 1px solid transparent; padding: 4px 10px; }}
QPushButton:hover, QComboBox:hover, QPushButton:pressed {{ background: {fg}; color: {bg}; }}
QPushButton:focus, QComboBox:focus {{ border-color: {fg}; }}
#new {{ border-color: {fg}; text-align: left; }}
QPushButton::menu-indicator {{ width: 0; }}
QComboBox::drop-down {{ border: none; width: 0; }}
QComboBox QAbstractItemView {{ border: 1px solid {fg}; padding: 4px; selection-background-color: {fg}; selection-color: {bg}; }}
QListWidget, QTextBrowser {{ border: none; }}
QListWidget::item {{ padding: 6px 8px; }}
QListWidget::item:selected, QListWidget::item:hover {{ background: {fg}; color: {bg}; }}
QPlainTextEdit, QLineEdit {{ border: 1px solid {fg}; padding: 8px; }}
QMenu {{ border: 1px solid {fg}; padding: 4px; }}
QMenu::item {{ padding: 4px 14px; }}
QMenu::item:selected {{ background: {fg}; color: {bg}; }}
*:disabled {{ border: 1px dashed {fg}; }}
QListWidget:disabled {{ border: none; }}
QSplitter::handle {{ background: {fg}; }}
QStatusBar {{ border-top: 1px solid {fg}; padding: 0 6px; }}
QStatusBar::item {{ border: none; }}
QScrollBar {{ border: none; width: 4px; height: 4px; }}
QScrollBar::handle {{ background: {fg}; min-height: 20px; min-width: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""


def two_colour_palette(fg, bg):
    """A palette where every role is fg or bg, so Qt never derives greys."""
    palette = QPalette()
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role in QPalette.ColorRole:
            if role != QPalette.NColorRoles:
                palette.setColor(group, role, fg)
        for role in (QPalette.Window, QPalette.Base, QPalette.AlternateBase,
                     QPalette.Button, QPalette.ToolTipBase, QPalette.HighlightedText):
            palette.setColor(group, role, bg)
    return palette


def stylesheet(fg, bg):
    return STYLE.format(fg=fg.name(), bg=bg.name(), font=FONT_FAMILY)
