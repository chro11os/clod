import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit


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

    def start(self, work):
        """Run work() on a worker thread, emitting whatever it yields, then done or failed."""
        def run():
            # Worker thread: never touch widgets here, only emit signals.
            try:
                for piece in work() or ():
                    self.piece.emit(piece)
                self.done.emit()
            except Exception as error:
                self.failed.emit(str(error))

        threading.Thread(target=run, daemon=True).start()


def compact(layout):
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(8)
    return layout
