# OwlThread - Universal Capture & Context Primer Engine

OwlThread ingests developer context ambiently across four surfaces, indexes project memory, and compiles instant **Context Primers** tailored to your task ("state your task, get context").

1. **Windows Clipboard Watcher** (core background poller).
2. **Pluggable File Connectors** (`CursorConnector` & `VSCodeCopilotConnector` implementing `IConnector`).
3. **CLI Execution Wrapper** (`owlthread run -- <command>` teeing stdout/stderr directly while capturing to memory).
4. **Browser Extension (Manifest V3)** (`Ctrl+Shift+O` shortcut capturing selection or active AI chat containers and POSTing to local HTTP server).
5. **Localhost HTTP Server & System Tray App** (Listening on `127.0.0.1:41789` for local ingestion and primer generation).
6. **Query & Primer Engine** (Lightweight intent classification, keyword + recency memory scoring, tailored LLM context compiler, auto-clipboard copy, and popup GUI).

---

## 1. Quick Start

### Installation
```powershell
# Install OwlThread in editable mode
python -m pip install -e .
```

### Launch System Tray App & Hotkey Listener
```powershell
# Launch System Tray App + Local HTTP Listener + Connectors + Clipboard Watcher + Global Hotkey (Ctrl+Shift+P)
owlthread start

# Or launch in headless terminal mode
owlthread start --headless
```

---

## 2. Query & Primer Engine ("State Task, Get Context")

The Query & Primer Engine turns your stored project memories into an actionable context brief:

1. **State your task**: Type a free-text description (e.g. *"integrate Stripe billing"*, *"I want to send this idea to an investor"*, *"audit new update"*).
2. **Intent Classification**: Automatically tagged as `dev_task`, `external_comms`, `status_query`, or `other`.
3. **Relevance Memory Search**: Queries `memory_entries` across all quadrants using token matching + exponential recency decay weighting.
4. **Primer Compilation**: Compiles the context using the specialized system prompt and intent-specific formatting rules.
5. **Auto-Copy & Preview**: Copies the resulting Markdown brief straight to your clipboard and previews it in the UI/terminal.

### Ways to State Your Task:
- **Global Hotkey**: Press <kbd>Ctrl+Shift+P</kbd> from anywhere on Windows.
- **System Tray Icon**: Right-click the Owl icon in the tray and select **"⚡ State Task & Get Primer..."**.
- **Visual Popup GUI**:
  ```powershell
  owlthread primer --ui
  ```
- **Terminal CLI**:
  ```powershell
  # Dev task brief
  owlthread primer "integrate Stripe billing"

  # Investor update / external pitch
  owlthread primer "I want to send this idea to an investor"

  # Status audit query
  owlthread primer "audit new update"
  ```
- **Local HTTP Endpoint**:
  ```http
  POST http://127.0.0.1:41789/primer
  Content-Type: application/json

  {
    "query": "integrate Stripe billing"
  }
  ```

---

## 3. Ingestion Surfaces

### A. Windows Clipboard
The background clipboard watcher automatically polls the Windows clipboard. When text changes, it saves a row to `memory_entries` with `source_app="clipboard"`.

### B. IDE File Connectors (`IConnector`)
- **`CursorConnector`**: Scans `%APPDATA%\Cursor\User\workspaceStorage\*\state.vscdb` (prompts, generations, composer data) and `globalStorage\conversation-search.db`.
- **`VSCodeCopilotConnector`**: Scans `%APPDATA%\Code\User\workspaceStorage\*\chatSessions\*.jsonl` and editing sessions.

### C. CLI Execution Wrapper
Wrap any developer CLI tool or LLM CLI to tee console output and capture the transcript:
```powershell
owlthread run -- claude
owlthread run -- python my_script.py
```

### D. Browser Extension (Manifest V3)
Located in `/extension`:
1. Open Chrome/Edge and navigate to `chrome://extensions`.
2. Toggle **Developer mode** (top right).
3. Click **Load unpacked** and select `C:\Users\AnshK\Downloads\OwlTherad\extension`.
4. Press <kbd>Ctrl+Shift+O</kbd> on any web page or AI chat interface to capture text to `http://127.0.0.1:41789/capture`.

---

## 4. CLI Commands Reference

| Command | Description |
|---|---|
| `owlthread primer "<task>"` | Generate context primer and copy to clipboard |
| `owlthread primer --ui` | Open the graphical Query & Primer popup dialog |
| `owlthread run -- <cmd>` | Run command with live output streaming & DB recording |
| `owlthread start` | Start system tray app, capture daemon, and hotkey listener |
| `owlthread start --headless` | Start capture engine in console mode |
| `owlthread entries` | View recently captured memory entries in terminal |
| `owlthread status` | Display capture engine health and DB entry counts |
| `owlthread test-capture <text>` | Manually insert a test capture row |

---

## 5. Automated Testing

Run the full test suite (57 tests):
```powershell
python -m unittest discover -s tests
```

---

## 6. 100% Free, Local-First & Fully Customizable

OwlThread is built on a **developer-first, open-source philosophy**:
- **100% Free & Open Source**: No monthly subscriptions, no gated enterprise paywalls, no cloud telemetry.
- **Local-First & Private**: All memories are stored locally in SQLite (`owlthread.db`). Your code and thoughts never leave your machine unless you configure a remote model.
- **Fully Customizable System Prompts**: Want to change how memories are extracted or how briefs are formatted? Edit prompts directly in the desktop app under **⚙️ Prompts & Settings** or via the SQLite `settings` table.
- **Tool-Agnostic Context Layer**: Doesn't fight with Cursor, Claude Code, or VS Code—serves as their ambient context supplier.

---

## 7. Run 100% Free with Local Ollama (Zero API Keys)

Don't want to pay for API keys? OwlThread natively connects to **Ollama** running locally on your machine (e.g. `llama3`, `deepseek-r1`, `mistral`, `qwen2.5-coder`):

1. Run your favorite local model:
   ```bash
   ollama run llama3
   ```
2. In OwlThread Desktop App -> **⚙️ Prompts & Settings**:
   - **Provider**: Select `Ollama (Localhost)`
   - **Model**: `llama3` (or your model name)
   - **Base URL**: `http://localhost:11434/v1`
   - **API Key**: (leave empty)
3. Click **⚡ Test Connection** -> You're running a completely free, private, offline memory engine!

---

## 8. Write Custom Plugins & Connectors (`IConnector`)

Want OwlThread to automatically pull context from **GitHub**, **Cloudflare**, **Jira**, or **Linear**?

Subclass `IConnector` and register it with the engine:

```python
from owlthread.capture.connectors.base import IConnector

class GitHubConnector(IConnector):
    """Watches local git commits or GitHub PRs for architectural decisions."""
    
    def start(self) -> None:
        super().start()
        # Initialize GitHub API client or git watchers

    def poll(self) -> int:
        # Fetch latest merged PRs or commit messages
        # Ingest into memory_entries
        return count_captured

    def stop(self) -> None:
        super().stop()
```

Register it in `owlthread/capture/engine.py`:
```python
engine.register_connector(GitHubConnector(db))
```

Fork on GitHub, customize your prompts, build connectors, and contribute back! 🦉🚀
