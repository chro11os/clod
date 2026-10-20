import json
from datetime import datetime
from pathlib import Path

CHATS_DIR = Path.home() / ".clod" / "chats"
TITLES = Path.home() / ".clod" / "titles.json"  # {chat_id: name} for renamed chats


def _titles():
    return json.loads(TITLES.read_text()) if TITLES.exists() else {}


def _save_titles(titles):
    TITLES.parent.mkdir(parents=True, exist_ok=True)
    TITLES.write_text(json.dumps(titles, indent=2))


def new_chat_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def save(chat_id, messages):
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    (CHATS_DIR / f"{chat_id}.json").write_text(json.dumps(messages, indent=2))


def load(chat_id):
    return json.loads((CHATS_DIR / f"{chat_id}.json").read_text())


def rename(chat_id, title):
    """Give a chat a custom name; an empty title goes back to the first question."""
    titles = _titles()
    if title:
        titles[chat_id] = title
    else:
        titles.pop(chat_id, None)
    _save_titles(titles)


def delete(chat_id):
    (CHATS_DIR / f"{chat_id}.json").unlink(missing_ok=True)
    titles = _titles()
    if titles.pop(chat_id, None) is not None:
        _save_titles(titles)


def list_chats():
    """Return (chat_id, title) pairs, newest first. Title = custom name or first question."""
    titles = _titles()
    chats = []
    for path in sorted(CHATS_DIR.glob("*.json"), reverse=True):
        title = titles.get(path.stem) or json.loads(path.read_text())[0]["content"][:40]
        chats.append((path.stem, title))
    return chats
