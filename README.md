# clod

Desktop AI coding harness for local Ollama models, built with PySide6 (Qt).

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com/download), then start Ollama.
2. Get the model clod is built on (9 GB):
   ```sh
   ollama pull huihui_ai/qwen3-abliterated:14b
   ```
   Or skip this and click **Download model…** in the app. That box starts out filled in with the same model.
3. Run it (uv installs the pinned Python and dependencies from `uv.lock`):
   ```sh
   git clone https://github.com/chro11os/clod.git && cd clod
   uv run clod
   ```

## Using your own model

Click **Download model…**, replace the name with any model from [ollama.com/library](https://ollama.com/library) (e.g. `llama3.2:3b`), then pick it from the dropdown. Models you already pulled with `ollama pull` show up there too.

## Layout

```
src/clod/
  app.py      # desktop window (PySide6)
  llm.py      # Ollama client (streaming)
  history.py  # saves chats to ~/.clod/chats/
```
