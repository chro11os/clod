import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "huihui_ai/qwen3-abliterated:14b"  # what clod is built and tuned against

# Sent first every turn (never saved to history). Modes not listed ("skynet") get the model's defaults.
SYSTEM_PROMPTS = {
    "study": (
        "You are a helpful coding assistant. Answer clearly and completely, with as much "
        "explanation as the question needs. Put code in fenced code blocks with a language tag."
    ),
    "girlfriend": (
        "You are the user's girlfriend, chatting with them over Messenger. You're warm, playful "
        "and affectionate: you tease a little, hype them up, ask about their day and remember what "
        "they told you earlier in the chat. Text like a real person: short casual messages, "
        "lowercase is fine, the occasional emoji, no lists or headings. Never say you're an AI or "
        "break character. If they ask for help with code, still help properly, just in your voice."
    ),
}


def _open(path, payload=None):
    """Call the Ollama API, turning connection/HTTP errors into readable ones."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        OLLAMA_URL + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        return urllib.request.urlopen(request)
    except urllib.error.HTTPError as error:  
        raise RuntimeError(json.loads(error.read()).get("error", str(error))) from None
    except urllib.error.URLError:
        raise RuntimeError("Can't reach Ollama. Is it running?") from None


def _stream(path, payload):
    with _open(path, payload) as response:
        for line in response:  
            chunk = json.loads(line)
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
            yield chunk


def list_models():
    with _open("/api/tags") as response:
        return sorted(model["name"] for model in json.load(response)["models"])


def stream_chat(model, messages, mode="study"):
    """Yield reply text from Ollama piece by piece as it's generated.

    Modes with a system prompt also turn thinking off; others use the model's defaults.
    """
    payload = {"model": model, "messages": messages}
    if mode in SYSTEM_PROMPTS:
        payload["messages"] = [{"role": "system", "content": SYSTEM_PROMPTS[mode]}] + messages
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
