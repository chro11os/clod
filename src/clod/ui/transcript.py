"""Draws a conversation into a QTextDocument: message bubbles, markdown, highlighted code."""

from functools import lru_cache

from pygments import lex
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound
from PySide6.QtCore import QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
)

AVATAR = QUrl("clod:skull")  # image resource name for the model's avatar
USER_INDENT = 160  # px your messages are pushed in from the left
MODEL_INDENT = 60  # px model replies stop short of the right edge

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


def render(document, messages, fg, bg, avatar):
    """Replace the document's contents with the messages."""
    document.clear()
    document.addResource(QTextDocument.ImageResource, AVATAR, avatar)
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
            frame.setBorderBrush(fg)
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
    style_code(document, fg, bg)


def style_code(document, fg, bg):
    """Monokai-highlight code blocks; draw `inline code` inverted (fg on bg)."""
    inline_format = QTextCharFormat()
    inline_format.setBackground(fg)
    inline_format.setForeground(bg)
    cursor = QTextCursor(document)
    block = document.begin()
    while block.isValid():
        if block.blockFormat().hasProperty(QTextFormat.BlockCodeFence):
            block = highlight_code_block(cursor, block)
            continue
        fragments = block.begin()
        while not fragments.atEnd():
            fragment = fragments.fragment()
            if fragment.charFormat().fontFixedPitch():
                cursor.setPosition(fragment.position())
                cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.KeepAnchor)
                cursor.mergeCharFormat(inline_format)
            fragments += 1
        block = block.next()


def highlight_code_block(cursor, block):
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
