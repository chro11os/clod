# clod

Desktop AI coding harness for local Ollama models, built with PySide6 (Qt).

## Run

```sh
uv run clod
```

Needs Ollama running locally. Pick or download models from the dropdown in the app.

## Layout

```
src/clod/
  app.py      # desktop window (PySide6)
  llm.py      # Ollama client (streaming)
  history.py  # saves chats to ~/.clod/chats/
```
