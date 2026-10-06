import sys
import threading
from functools import lru_cache

from pygments import lex
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound
from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QActionGroup,
    QColor,
    QFont,
    QGuiApplication,
    QKeySequence,
    QPalette,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from clod import history
from clod.llm import list_models, pull_model, stream_chat, warm_model
from clod.skull import Splash, pixel_skull

FONT_FAMILY = "Iosevka Nerd Font"
INK = QColor("#111111")
PAPER = QColor("#fafafa")
MODES = {  # settings menu: mode -> label
    "study": "Study: barebones snippets, no thinking",
    "skynet": "Skynet: model's default behaviour",
}
AVATAR = QUrl("clod:skull")  # image resource name for the model's avatar
USER_INDENT = 160  # px your messages are pushed in from the left
MODEL_INDENT = 60  # px model replies stop short of the right edge


# The whole UI uses only two colours: fg (text, borders) and bg (background).
# Light theme = ink on paper, dark theme = paper on ink. Emphasis = invert.
STYLE = """
* {{ background: {bg}; color: {fg}; placeholder-text-color: {fg}; font-family: "{font}"; font-size: 13pt; }}
QToolBar {{ border: none; border-bottom: 1px solid {fg}; padding: 2px; spacing: 4px; }}
QPushButton, QComboBox {{ border: 1px solid {fg}; padding: 2px 8px; }}
QPushButton:hover, QComboBox:hover {{ background: {fg}; color: {bg}; }}
QComboBox QAbstractItemView {{ border: 1px solid {fg}; selection-background-color: {fg}; selection-color: {bg}; }}
QListWidget, QTextBrowser, QPlainTextEdit, QLineEdit {{ border: 1px solid {fg}; }}
QListWidget::item:selected, QListWidget::item:hover {{ background: {fg}; color: {bg}; }}
QMenu {{ border: 1px solid {fg}; }}
QMenu::item {{ padding: 2px 12px; }}
QMenu::item:selected {{ background: {fg}; color: {bg}; }}
*:disabled {{ border-style: dashed; }}
QSplitter::handle {{ background: {fg}; }}
QProgressBar {{ border: none; max-height: 3px; }}
QProgressBar::chunk {{ background: {fg}; }}
QStatusBar {{ border-top: 1px solid {fg}; }}
QScrollBar {{ border: none; width: 8px; height: 8px; }}
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


# Code blocks are the one exception to ink/paper: Monokai, on its own background.
MONOKAI = get_style_by_name("monokai")
MONOKAI_BG = QColor(MONOKAI.background_color)


def lexer_for(language):
    # stripnl/ensurenl off so token positions line up exactly with the document
    try:
        return get_lexer_by_name(language, stripnl=False, ensurenl=False)
    except ClassNotFound:  # unknown or missing language: plain text
        return TextLexer(stripnl=False, ensurenl=False)


@lru_cache
def monokai_format(token):
    style = MONOKAI.style_for_token(token)
    char_format = QTextCharFormat()
    char_format.setForeground(QColor("#" + (style["color"] or "f8f8f2")))
    char_format.setBackground(MONOKAI_BG)
    char_format.setFontWeight(QFont.Bold if style["bold"] else QFont.Normal)
    char_format.setFontItalic(style["italic"])
    return char_format


@lru_cache(maxsize=256)
def first_block_format(markdown):
    """Block format (code fence, heading...) of the markdown's first paragraph."""
    document = QTextDocument()
    document.setMarkdown(markdown)
    return document.begin().blockFormat()


class PromptBox(QPlainTextEdit):
    """Text box where Enter sends and Shift+Enter adds a new line."""

    submitted = Signal()

    def keyPressEvent(self, event):
        is_enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        if is_enter and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
        else:
            super().keyPressEvent(event)


class Stream(QObject):
    # Signals safely carry output from a worker thread to the UI thread.
    piece = Signal(str)
    done = Signal()
    failed = Signal(str)


def compact(layout):
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(4)
    return layout


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("clod")
        self.resize(1000, 700)
        self.settings = QSettings("clod", "clod")  # remembers model, theme + mode

        self.chat_id = history.new_chat_id()
        self.messages = []  # full conversation, sent to the model every turn
        self.reply = ""  # assistant text currently streaming in
        self.busy = False
        self.render_pending = False

        # Top bar: model picker, download, theme toggle
        self.model_box = QComboBox()
        self.model_box.setMinimumWidth(220)
        self.model_box.currentTextChanged.connect(self.choose_model)
        self.download_button = QPushButton("Download model…")
        self.download_button.clicked.connect(self.download_model)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.theme_button = QPushButton()
        self.theme_button.clicked.connect(self.toggle_theme)
        self.settings_button = QPushButton("Settings")
        self.settings_button.setMenu(self.settings_menu())
        toolbar = QToolBar()
        toolbar.setMovable(False)
        for widget in (self.model_box, self.download_button, spacer, self.settings_button, self.theme_button):
            toolbar.addWidget(widget)
        self.addToolBar(toolbar)

        # Left side: new chat button + saved chats
        self.new_button = QPushButton("New chat")
        self.new_button.clicked.connect(self.new_chat)
        self.sidebar = QListWidget()
        self.sidebar.itemClicked.connect(self.open_saved_chat)
        self.sidebar.setContextMenuPolicy(Qt.CustomContextMenu)  # right-click: rename/delete
        self.sidebar.customContextMenuRequested.connect(self.chat_menu)
        left = QWidget()
        left_layout = compact(QVBoxLayout(left))
        left_layout.addWidget(self.new_button)
        left_layout.addWidget(self.sidebar)

        # Right side: conversation + prompt box
        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        self.transcript.document().setDocumentMargin(6)
        self.prompt = PromptBox()
        self.prompt.setPlaceholderText("Ask something…  (Enter to send, Shift+Enter for new line)")
        self.prompt.setFixedHeight(70)
        self.prompt.submitted.connect(self.send)
        right = QWidget()
        right_layout = compact(QVBoxLayout(right))
        right_layout.addWidget(self.transcript)
        self.loading = QProgressBar()  # shown while the model answers
        self.loading.setRange(0, 0)  # no known end: Qt animates it as "busy"
        self.loading.setTextVisible(False)
        self.loading.hide()
        right_layout.addWidget(self.loading)
        right_layout.addWidget(self.prompt)

        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([220, 780])
        self.setCentralWidget(splitter)
        self.statusBar().setSizeGripEnabled(False)

        QShortcut(QKeySequence.New, self).activated.connect(self.new_chat)  # Cmd+N

        self.chat_stream = Stream()
        self.chat_stream.piece.connect(self.on_piece)
        self.chat_stream.done.connect(self.on_done)
        self.chat_stream.failed.connect(self.on_failed)

        self.pull_stream = Stream()
        self.pull_stream.piece.connect(self.statusBar().showMessage)
        self.pull_stream.done.connect(self.on_pull_done)
        self.pull_stream.failed.connect(self.on_pull_failed)
        self.pulling = None  # name of the model being downloaded

        self.warm_stream = Stream()
        self.warm_stream.done.connect(self.on_warm_done)
        self.warm_stream.failed.connect(self.on_warm_failed)
        self.warming = None  # name of the model being loaded into memory

        system_dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        self.apply_theme(self.settings.value("theme", "dark" if system_dark else "light"))
        self.refresh_models(self.settings.value("model"))
        self.refresh_history()
        self.prompt.setFocus()

    # --- models -----------------------------------------------------------

    @property
    def model(self):
        return self.model_box.currentText()

    def refresh_models(self, select=None):
        try:
            models = list_models()
        except RuntimeError as error:
            self.statusBar().showMessage(f"Error: {error}")
            return
        self.model_box.blockSignals(True)  # don't save a choice while refilling
        self.model_box.clear()
        self.model_box.addItems(models)
        if select in models:
            self.model_box.setCurrentText(select)
        self.model_box.blockSignals(False)
        self.choose_model(self.model)  # once, by hand: signals were blocked above

    def choose_model(self, name):
        if name:
            self.settings.setValue("model", name)
            self.warm(name)

    def warm(self, name):
        """Load the model into memory in the background, so the first reply is quick."""
        self.warming = name
        self.statusBar().showMessage(f"Loading {name}…")
        threading.Thread(target=self.run_warm, args=(name,), daemon=True).start()

    def run_warm(self, name):
        # Worker thread: never touch widgets here, only emit signals.
        try:
            warm_model(name)
            self.warm_stream.done.emit()
        except Exception as error:
            self.warm_stream.failed.emit(str(error))

    def on_warm_done(self):
        # ponytail: a fast model switch can label the wrong model "ready"; cosmetic only
        self.statusBar().showMessage(f"{self.warming} ready", 3000)
        self.warming = None

    def on_warm_failed(self, error):
        self.statusBar().showMessage(f"Couldn't load {self.warming}: {error}")
        self.warming = None

    def download_model(self):
        name, ok = QInputDialog.getText(
            self, "Download model", "Model name from ollama.com/library (e.g. llama3.2:3b):"
        )
        name = name.strip()
        if not ok or not name:
            return
        self.pulling = name
        self.download_button.setEnabled(False)
        self.statusBar().showMessage(f"Downloading {name}…")
        threading.Thread(target=self.run_pull, args=(name,), daemon=True).start()

    def run_pull(self, name):
        # Worker thread: never touch widgets here, only emit signals.
        try:
            for progress in pull_model(name):
                self.pull_stream.piece.emit(f"{name}: {progress}")
            self.pull_stream.done.emit()
        except Exception as error:
            self.pull_stream.failed.emit(str(error))

    def on_pull_done(self):
        self.download_button.setEnabled(True)
        self.statusBar().showMessage(f"Downloaded {self.pulling}", 5000)
        if not self.busy:  # don't switch models mid-reply
            self.refresh_models(select=self.pulling)

    def on_pull_failed(self, error):
        self.download_button.setEnabled(True)
        self.statusBar().showMessage(f"Download failed: {error}")

    # --- settings ---------------------------------------------------------

    @property
    def mode(self):
        return self.settings.value("mode", "study")

    def settings_menu(self):
        menu = QMenu(self)
        group = QActionGroup(menu)  # exclusive: one mode at a time
        for mode, label in MODES.items():
            action = group.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == self.mode)
            action.setData(mode)
            menu.addAction(action)
        group.triggered.connect(lambda action: self.settings.setValue("mode", action.data()))
        return menu

    # --- theme ------------------------------------------------------------

    def apply_theme(self, theme):
        self.settings.setValue("theme", theme)
        self.theme = theme
        self.fg, self.bg = (PAPER, INK) if theme == "dark" else (INK, PAPER)
        self.avatar = pixel_skull(self.fg, self.devicePixelRatio())
        app = QApplication.instance()
        app.setPalette(two_colour_palette(self.fg, self.bg))
        app.setStyleSheet(STYLE.format(fg=self.fg.name(), bg=self.bg.name(), font=FONT_FAMILY))
        self.theme_button.setText("☀ Light" if theme == "dark" else "☾ Dark")
        self.render()  # redraw so text picks up the new colours

    def toggle_theme(self):
        self.apply_theme("light" if self.theme == "dark" else "dark")

    # --- chats ------------------------------------------------------------

    def refresh_history(self):
        self.sidebar.clear()
        for chat_id, title in history.list_chats():
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, chat_id)
            self.sidebar.addItem(item)

    def render(self):
        self.render_pending = False
        messages = self.messages
        if self.reply:
            messages = messages + [{"role": "assistant", "content": self.reply}]

        document = self.transcript.document()
        document.clear()
        document.addResource(QTextDocument.ImageResource, AVATAR, self.avatar)
        cursor = QTextCursor(document)
        gap = QTextBlockFormat()  # the empty line between messages, kept thin
        gap.setLineHeight(6, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
        cursor.setBlockFormat(gap)
        for message in messages:
            # Each message gets its own frame: yours a bubble on the right,
            # the model's on the left, like a messaging app.
            frame = QTextFrameFormat()
            frame.setPadding(8)
            if message["role"] == "user":
                frame.setLeftMargin(USER_INDENT)
                frame.setBorder(1)
                frame.setBorderBrush(self.fg)
                frame.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
            else:
                frame.setRightMargin(MODEL_INDENT)
            cursor.insertFrame(frame)
            if message["role"] != "user":
                cursor.insertImage(AVATAR.toString())  # 8-bit skull on its own line
                cursor.insertBlock()
            start = cursor.position()
            cursor.insertMarkdown(message["content"])
            # insertMarkdown merges the first paragraph into the frame's empty line
            # and drops its format (code block, heading), so put it back.
            first_block = QTextCursor(document.findBlock(start))
            first_block.setBlockFormat(first_block_format(message["content"]))
            cursor.movePosition(QTextCursor.End)  # step back out of the frame
            cursor.setBlockFormat(gap)
        self.style_code()
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def style_code(self):
        """Monokai-highlight code blocks; draw `inline code` inverted (fg on bg)."""
        inline_format = QTextCharFormat()
        inline_format.setBackground(self.fg)
        inline_format.setForeground(self.bg)
        cursor = QTextCursor(self.transcript.document())
        block = self.transcript.document().begin()
        while block.isValid():
            if block.blockFormat().hasProperty(QTextFormat.BlockCodeFence):
                block = self.highlight_code_block(cursor, block)
                continue
            fragments = block.begin()
            while not fragments.atEnd():
                fragment = fragments.fragment()
                if fragment.charFormat().fontFixedPitch():  # inline `code`
                    cursor.setPosition(fragment.position())
                    cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.KeepAnchor)
                    cursor.mergeCharFormat(inline_format)
                fragments += 1
            block = block.next()

    def highlight_code_block(self, cursor, block):
        """Colour one fenced code block (a run of code lines); return the block after it."""
        start = block.position()
        language = block.blockFormat().stringProperty(QTextFormat.BlockCodeLanguage)
        background = QTextBlockFormat()
        background.setBackground(MONOKAI_BG)
        lines = []
        while (
            block.isValid()
            and block.blockFormat().hasProperty(QTextFormat.BlockCodeFence)
            and block.blockFormat().stringProperty(QTextFormat.BlockCodeLanguage) == language
        ):
            cursor.setPosition(block.position())
            cursor.mergeBlockFormat(background)
            lines.append(block.text())
            block = block.next()
        # Lines are joined with "\n", which takes one position just like a block break.
        position = start
        for token, text in lex("\n".join(lines), lexer_for(language)):
            cursor.setPosition(position)
            cursor.setPosition(position + len(text), QTextCursor.KeepAnchor)
            cursor.mergeCharFormat(monokai_format(token))
            position += len(text)
        return block

    def open_chat(self, chat_id, messages):
        self.chat_id = chat_id
        self.messages = messages
        self.render()
        self.prompt.setFocus()

    def new_chat(self):
        if not self.busy:
            self.open_chat(history.new_chat_id(), [])

    def open_saved_chat(self, item):
        chat_id = item.data(Qt.UserRole)
        self.open_chat(chat_id, history.load(chat_id))

    def chat_menu(self, position):
        item = self.sidebar.itemAt(position)
        if not item:
            return
        menu = QMenu(self)
        rename = menu.addAction("Rename…")
        delete = menu.addAction("Delete")
        chosen = menu.exec(self.sidebar.mapToGlobal(position))
        if chosen == rename:
            self.rename_chat(item)
        elif chosen == delete:
            self.delete_chat(item)

    def rename_chat(self, item):
        title, ok = QInputDialog.getText(
            self, "Rename chat", "Name (leave empty to use the first question):", text=item.text()
        )
        if ok:
            history.rename(item.data(Qt.UserRole), title.strip())
            self.refresh_history()

    def delete_chat(self, item):
        answer = QMessageBox.question(self, "Delete chat", f"Delete “{item.text()}”? This can't be undone.")
        if answer != QMessageBox.Yes:
            return
        chat_id = item.data(Qt.UserRole)
        history.delete(chat_id)
        self.refresh_history()
        if chat_id == self.chat_id:  # deleted the open chat: start fresh
            self.new_chat()

    def set_busy(self, busy):
        # Lock input, chat switching and model switching while the model answers.
        self.busy = busy
        self.loading.setVisible(busy)
        for widget in (self.prompt, self.sidebar, self.new_button, self.model_box):
            widget.setEnabled(not busy)
        if not busy:
            self.prompt.setFocus()

    def send(self):
        text = self.prompt.toPlainText().strip()
        if not text or self.busy:
            return
        if not self.model:
            self.statusBar().showMessage("No model selected. Download one first.")
            return
        self.prompt.clear()
        self.statusBar().clearMessage()
        self.messages.append({"role": "user", "content": text})
        self.reply = ""
        self.set_busy(True)
        self.render()
        args = (self.model, list(self.messages), self.mode == "study")
        threading.Thread(target=self.run_model, args=args, daemon=True).start()

    def run_model(self, model, messages, study):
        # Worker thread: never touch widgets here, only emit signals.
        try:
            for piece in stream_chat(model, messages, study):
                self.chat_stream.piece.emit(piece)
            self.chat_stream.done.emit()
        except Exception as error:
            self.chat_stream.failed.emit(str(error))

    def on_piece(self, piece):
        self.reply += piece
        if not self.render_pending:  # redraw ~20x/sec instead of on every token
            self.render_pending = True
            QTimer.singleShot(50, self.render)

    def on_done(self):
        self.messages.append({"role": "assistant", "content": self.reply})
        self.reply = ""
        history.save(self.chat_id, self.messages)
        self.refresh_history()
        self.set_busy(False)
        self.render()

    def on_failed(self, error):
        question = self.messages.pop()  # drop the unanswered question...
        self.prompt.setPlainText(question["content"])  # ...but give it back to retry
        self.reply = ""
        self.set_busy(False)
        self.render()
        self.statusBar().showMessage(f"Error: {error}")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # plain style we can fully recolour (native adds greys)
    app.setFont(QFont(FONT_FAMILY, 13))
    window = MainWindow()  # starts loading the model in the background
    splash = Splash(window)  # shows the window itself once the model is loaded
    splash.show()
    sys.exit(app.exec())
