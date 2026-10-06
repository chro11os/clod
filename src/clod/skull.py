import random
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy

SKULL = r"""
           .-''''''''''''''-.
        .-'                  '-.
       /                        \
      |                          |
      |   .------.    .------.   |
      |  /        \  /        \  |
      |  |   ()   |  |   ()   |  |
      |  \        /  \        /  |
       \  '------'    '------'  /
        '.         /\         .'
         |        /__\        |
         |                    |
          \  |_|_|_|_|_|_|_|  /
           '.|_|_|_|_|_|_|_|.'
             '--------------'
""".strip("\n").splitlines()
WIDTH = max(map(len, SKULL)) + 8  # 4 spaces each side, room for glitch tears
GLITCH = "░▒▓█#@%$&01/\\"
MIN_SECONDS = 1.6  # show the animation at least this long, even if the model is warm


def glitch_frame(tick, status, rng=random):
    """One frame of the skull: random glyph noise, sideways tears, blinking X eyes."""
    heavy = rng.random() < 0.08  # now and then a big glitch burst
    noise, tear = (0.2, 0.3) if heavy else (0.02, 0.03)
    lines = []
    for line in SKULL:
        if tick % 24 < 3:
            line = line.replace("()", "><")
        line = "".join(c if c == " " or rng.random() > noise else rng.choice(GLITCH) for c in line)
        line = line.ljust(WIDTH - 4).rjust(WIDTH)
        if rng.random() < tear:
            shift = rng.randint(-3, 3)
            line = line[-shift:] + line[:-shift]
        lines.append(line)
    dots = "." * (tick // 4 % 4)
    cursor = "█" if tick // 5 % 2 else " "
    lines += ["", f"> {status}{dots:<3}{cursor}".center(WIDTH)]
    return "\n".join(lines)


class Splash(QLabel):
    """Glitchy ASCII skull shown while the starting model loads. Click to skip."""

    def __init__(self, window):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        self.window = window
        self.status = f"waking {window.model}" if window.model else "no model loaded"
        self.started = time.monotonic()
        self.tick = 0
        self.setTextFormat(Qt.PlainText)
        self.setStyleSheet(f"border: 1px solid {window.fg.name()}; padding: 24px;")
        self.animate()
        self.adjustSize()
        self.move(self.screen().availableGeometry().center() - self.rect().center())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(80)

    def animate(self):
        self.tick += 1
        self.setText(glitch_frame(self.tick, self.status))
        if time.monotonic() - self.started > MIN_SECONDS and not self.window.warming:
            self.finish()

    def mousePressEvent(self, event):
        self.finish()

    def finish(self):
        self.timer.stop()
        self.window.show()  # before closing, so the app never has zero windows
        self.close()


class Noise(QLabel):
    """One line of sparse, flickering glyphs: a signal being picked up. Animates only while shown."""

    def __init__(self):
        super().__init__()
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)  # text never widens the layout
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.flicker)

    def flicker(self):
        count = self.width() // max(1, self.fontMetrics().horizontalAdvance("#"))
        self.setText("".join(random.choice(GLITCH) if random.random() < 0.25 else " " for _ in range(count)))

    def showEvent(self, event):
        self.flicker()
        self.timer.start(70)

    def hideEvent(self, event):
        self.timer.stop()


# 8-bit skull for the model's chat avatar: "#" = pixel in the text colour.
PIXEL_SKULL = (
    "...#######...",
    ".###########.",
    "#############",
    "#############",
    "##...###...##",
    "##...###...##",
    "##...###...##",
    "######.######",
    ".####...####.",
    "..#########..",
    "..#.#.#.#.#..",
    "..#########..",
)


def pixel_skull(color, pixel_ratio, cell=2):
    """The pixel skull as a crisp image: each "#" is a cell×cell (logical px) square."""
    scale = round(cell * pixel_ratio)
    image = QImage(len(PIXEL_SKULL[0]) * scale, len(PIXEL_SKULL) * scale, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    for y, row in enumerate(PIXEL_SKULL):
        for x, pixel in enumerate(row):
            if pixel == "#":
                painter.fillRect(x * scale, y * scale, scale, scale, color)
    painter.end()
    image.setDevicePixelRatio(scale / cell)
    return image


if __name__ == "__main__":  # self-check: frames keep a fixed size so the splash never jitters
    sizes = {tuple(map(len, glitch_frame(t, "waking test").splitlines())) for t in range(500)}
    assert len(sizes) == 1, sizes
    print(glitch_frame(0, "waking qwen2.5-coder:7b", random.Random(1)))
