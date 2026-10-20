from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QActionGroup, QDesktopServices, QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from clod.core import history
from clod.core.llm import DEFAULT_MODEL, list_models, pull_model, stream_chat, warm_model
from clod.ui import transcript
from clod.ui.skull import pixel_skull
from clod.ui.theme import INK, PAPER, stylesheet, two_colour_palette
from clod.ui.widgets import PromptBox, Stream, compact

MODES = {  # settings menu: mode -> label
    "study": "Study: coding assistant, no thinking",
    "skynet": "Skynet: model's default behaviour",
    "girlfriend": "Girlfriend: texts you like your partner",
}
CARET = " █"  # redaction block trailing a reply while it streams in
TYPING = ("● ○ ○", "○ ● ○", "○ ○ ●")  # Messenger-style dots shown until the first word arrives


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
        self.typing_frame = 0
        self.typing = QTimer(self)  # steps the typing dots while waiting for the reply
        self.typing.timeout.connect(self.step_typing)

        # Top bar: sigil, model picker, download, theme toggle
        self.sigil = QLabel()
        wordmark = QLabel("clod")
        wordmark.setStyleSheet("font-weight: bold; letter-spacing: 3px; padding-right: 12px;")
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
        for widget in (self.sigil, wordmark, self.model_box, self.download_button, spacer, self.settings_button, self.theme_button):
            toolbar.addWidget(widget)
        self.addToolBar(toolbar)

        # left side: new chat button + saved chats
        self.new_button = QPushButton("+ New chat")
        self.new_button.setObjectName("new")
        self.new_button.clicked.connect(self.new_chat)
        self.sidebar = QListWidget()
        self.sidebar.itemClicked.connect(self.open_saved_chat)
        self.sidebar.setContextMenuPolicy(Qt.CustomContextMenu)  # right-click: rename/delete
        self.sidebar.customContextMenuRequested.connect(self.chat_menu)
        left = QWidget()
        left_layout = compact(QVBoxLayout(left))
        left_layout.addWidget(self.new_button)
        left_layout.addWidget(self.sidebar)

        # right side: conversation + prompt box
        self.transcript = QTextBrowser()
        # eh idk, should i just keep the file links opening? virus for everyone how bout that? (this keeps the llm from opening and submitting links sheesh)
        self.transcript.setOpenLinks(False)
        self.transcript.anchorClicked.connect(
            lambda url: url.scheme() in ("http", "https") and QDesktopServices.openUrl(url)
        )
        self.transcript.document().setDocumentMargin(6)
        self.prompt = PromptBox()
        self.prompt.setPlaceholderText("Ask anything.  Enter sends, Shift+Enter adds a line")
        self.prompt.setFixedHeight(84)
        self.prompt.submitted.connect(self.send)
        right = QWidget()
        right_layout = compact(QVBoxLayout(right))
        right_layout.addWidget(self.transcript)
        right_layout.addWidget(self.prompt)

        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([220, 780])
        self.setCentralWidget(splitter)
        self.statusBar().setSizeGripEnabled(False)
        # True as long as llm.OLLAMA_URL is localhost.
        self.statusBar().addPermanentWidget(QLabel("offline. nothing leaves this machine"))

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
        if not models:
            self.statusBar().showMessage("No models yet. Click “Download model…” to get one.")

    def choose_model(self, name):
        if name:
            self.settings.setValue("model", name)
            self.warm(name)

    def warm(self, name):
        """Load the model into memory in the background, so the first reply is quick."""
        self.warming = name
        self.statusBar().showMessage(f"Loading {name}…")
        self.warm_stream.start(lambda: warm_model(name))

    def on_warm_done(self):
        # ponytail: a fast model switch can label the wrong model "ready"; cosmetic only
        self.statusBar().showMessage(f"{self.warming} ready", 3000)
        self.warming = None

    def on_warm_failed(self, error):
        self.statusBar().showMessage(f"Couldn't load {self.warming}: {error}")
        self.warming = None

    def download_model(self):
        name, ok = QInputDialog.getText(
            self,
            "Download model",
            "Model name from ollama.com/library. The default is the one clod is built on;\n"
            "replace it to download your own (e.g. llama3.2:3b):",
            text=DEFAULT_MODEL,
        )
        name = name.strip()
        if not ok or not name:
            return
        self.pulling = name
        self.download_button.setEnabled(False)
        self.statusBar().showMessage(f"Downloading {name}…")
        self.pull_stream.start(lambda: (f"{name}: {progress}" for progress in pull_model(name)))

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
        self.sigil.setPixmap(QPixmap.fromImage(self.avatar))
        app = QApplication.instance()
        app.setPalette(two_colour_palette(self.fg, self.bg))
        app.setStyleSheet(stylesheet(self.fg, self.bg))
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

    def render(self, to_bottom=False):
        self.render_pending = False
        messages = self.messages
        if self.reply:
            messages = messages + [{"role": "assistant", "content": self.reply + CARET}]
        elif self.busy:
            messages = messages + [{"role": "assistant", "content": TYPING[self.typing_frame % len(TYPING)]}]
        scrollbar = self.transcript.verticalScrollBar()
        # Follow the reply only if you're already at the bottom; otherwise stay where you scrolled.
        to_bottom = to_bottom or scrollbar.value() >= scrollbar.maximum() - 4
        position = scrollbar.value()
        transcript.render(self.transcript.document(), messages, self.fg, self.bg, self.avatar)
        scrollbar.setValue(scrollbar.maximum() if to_bottom else position)

    def open_chat(self, chat_id, messages):
        self.chat_id = chat_id
        self.messages = messages
        self.render(to_bottom=True)
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
        if busy:
            self.typing.start(350)
        else:
            self.typing.stop()
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
        self.render(to_bottom=True)
        model, messages, mode = self.model, list(self.messages), self.mode
        self.chat_stream.start(lambda: stream_chat(model, messages, mode))

    def step_typing(self):
        self.typing_frame += 1
        self.render()

    def on_piece(self, piece):
        self.reply += piece
        if self.reply:  # first real text: dots give way to the reply (thinking chunks are empty)
            self.typing.stop()
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

