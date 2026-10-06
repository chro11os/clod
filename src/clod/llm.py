import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434"

# Sent first every turn (never saved to history) to keep replies to just the snippet.
SYSTEM_PROMPT = (
    "You are a terse coding assistant. First decide if the message asks for code.\n"
    "If it asks for code: reply with only the bare minimum snippet that does it, in one "
    "fenced code block with a language tag. No text before or after it. No example usage, "
    "sample data, print statements, main blocks, comments, or imports that aren't required. "
    "Use the fewest lines that are still valid code, but never join statements with semicolons.\n"
    "Otherwise (greetings, chat, questions): reply in one short plain-text sentence. "
    "Never use a code block for these, and never just repeat or quote the message back.\n"
    "Examples:\n"
    "User: python reverse a string\nYou:\n```python\ns[::-1]\n```\n"
    "User: yo\nYou: Hey, what do you need?\n"
    "User: what does git rebase do\nYou: It replays your commits on top of another branch."
)


def _open(path, payload=None):
    """Call the Ollama API, turning connection/HTTP errors into readable ones."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        OLLAMA_URL + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        return urllib.request.urlopen(request)
    except urllib.error.HTTPError as error:  # e.g. model not installed
        raise RuntimeError(json.loads(error.read()).get("error", str(error))) from None
    except urllib.error.URLError:
        raise RuntimeError("Can't reach Ollama. Is it running?") from None


def _stream(path, payload):
    with _open(path, payload) as response:
        for line in response:  # Ollama streams one JSON object per line
            chunk = json.loads(line)
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
            yield chunk


def list_models():
    with _open("/api/tags") as response:
        return sorted(model["name"] for model in json.load(response)["models"])


def stream_chat(model, messages, study=True):
    """Yield reply text from Ollama piece by piece as it's generated.

    study: barebones snippets, thinking off. Otherwise ("skynet") the model's defaults.
    """
    payload = {"model": model, "messages": messages}
    if study:
        payload["messages"] = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        # think off: thinking models (qwen3...) otherwise reason for 10-30s before a 1-line snippet
        payload["think"] = False
    for chunk in _stream("/api/chat", payload):
        yield chunk["message"]["content"]


def warm_model(model):
    """Load a model into memory now (Ollama does this for an empty prompt)."""
    with _open("/api/generate", {"model": model}) as response:
        response.read()


def pull_model(name):
    """Download a model, yielding progress text like 'pulling 4.2 GB 37%'."""
    for chunk in _stream("/api/pull", {"model": name}):
        if chunk.get("total"):
            percent = chunk.get("completed", 0) / chunk["total"]
            yield f"{chunk['status']} — {chunk['total'] / 1e9:.1f} GB {percent:.0%}"
        else:
            yield chunk["status"]
