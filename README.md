# OwlThread 1.7.0

**State your task, get context.** OwlThread keeps project memory on your computer and produces a cited Markdown brief for the task you describe. The desktop, command line, browser companion and MCP tools share one SQLite database.

This is a release candidate. See [verification](docs/VERIFICATION.md) for measured results and unfinished validation. Windows is the primary platform; current IDE formats and live AI-site observers remain experimental.

## What works, and what has been tested

| Area | Status and evidence boundary |
| --- | --- |
| Durable capture, projects, atomic extraction/rebase, BM25 search | Implemented; tested with real SQLite, concurrent processes and restart fixtures |
| Desktop feed, search, four quadrants, settings, primer | Implemented; tested with real Tk widgets and workers |
| Browser no-selection capture and authenticated pairing | Implemented; current AI turn or sanitized visible page is queued locally before acknowledgement |
| Companion, offline queue, navigation, motion and site refusal | Exercised in installed Chrome and Brave with synthetic pages; transport mocked in the visual suite |
| ChatGPT, Claude and DeepSeek response observers | Experimental; DOM fixtures tested, live signed-in services not certified |
| Cursor and VS Code Copilot | Experimental, opt-in; parser and workspace fixtures tested; changing live storage formats not certified |
| Git metadata and selected diffs | Implemented explicit opt-in command; temporary real Git repositories tested |
| Provider adapters | Request/error fixtures tested; no paid-provider credential test or local Ollama model run in this audit |
| MCP | Real stdio client/server and packaged executable smoke tests; see verification for exact results |
| Built-in Cloudflare/GitHub context clients and 29-service catalog | Browser sign-in, discovered account/repository choices and explicit context import are bundled. All other services show Coming soon |
| Cloud sync, semantic embeddings, generic browser history, background Git watching | Not implemented |
| Firefox/Safari extension, signed installer, macOS/Linux native desktop release | Unsupported in this release |

## Install on Windows

Release files are under `artifacts/release/1.7.0/`. Extract `OwlThread-Windows-1.7.0.zip` into a new folder. Keep the complete folder together. Use **Open OwlThread.bat** for the desktop or **Start tray.bat** for the background app. `owlthread-cli.exe --version` reports the version. No separate Python is required for the portable build. The binaries are unsigned.

From source, use Python 3.11+ with Tk support (this audit used Windows Python 3.14):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m owlthread app
```

After installing from source, double-click `run.bat` (or `Launch_OwlThread.bat`) to open the desktop. `run_owlthread.bat` does the same. For command-line use, run `.\owlthread.cmd status` or `.\owlthread.cmd run -- <your command>` from PowerShell. Startup failures show a Windows error dialog; the console command prints the full error.

For the exact Windows build environment, install `requirements-windows.lock` before installing the project with `--no-deps --no-build-isolation`. The lock contains runtime and build dependencies, not unrelated packages from the developer's environment. Other platforms resolve the ranges in `pyproject.toml` and are not covered by this Windows lock.

## First use and privacy choices

1. Open desktop Settings. Leave provider **Fallback** for entirely local rule-based extraction and brief assembly. Existing provider environment variables are also supported; inspect them if source launches unexpectedly select a provider.

   For Groq, select **Groq**, use `qwen/qwen3.8-27b`, and enter your key in Settings. Source launches also recognize `GROQ_API_KEY`. Durable memory extraction (including UPDATE/SUPERSEDE decisions) and context primers use **medium reasoning**: these tasks must distinguish commitments from suggestions, reconcile existing facts and connect relevant evidence. Their shared reasoning-and-answer budget is 4,096 tokens; briefs still must fit 500 words. Simple intent classification, page summaries and the legacy importance gate disable reasoning. Reasoning stays separate from saved text, and the primer cache includes generation settings. This is a workload-based default, not a measured claim that medium always outperforms low. The adapter collects complete responses before JSON validation. Keys remain in the desktop's protected settings, never the browser extension or source code.
2. **Strict site isolation is on by default.** It disables clipboard monitoring even if an older setting enabled it, because clipboard text has no trustworthy source website. Turn strict isolation off only if you knowingly prefer origin-blind clipboard capture. IDE monitoring remains opt-in. Restart after source changes.
3. Select or create a project in the desktop header. Capture a note such as `Decision: Use SQLite WAL for durable local writes.` Choose extraction, or run `owlthread done`.
4. Press **Ctrl+Shift+P** while the desktop or tray is running, describe a task, and generate a brief. The result reports whether copying succeeded. Shortcut conflicts may require the tray menu or desktop Primer view.

## Browser installation and pairing

Extract `OwlThread-Chrome-Brave-1.7.0.zip`, or use the Windows package's `extension` folder. In Chrome/Brave's extensions page, enable Developer mode and choose **Load unpacked** on the folder containing `manifest.json`. Reload the extension and refresh websites after an update.

In desktop Settings, choose **Copy pairing secret**. Paste it only into the OwlThread popup's **Preferences & connection → Connection settings**, then pair. The secret grants access to local memory; do not paste it into a web page or chat. Choose a capture project in the same popup. Each browser pairs separately with the same desktop at `127.0.0.1:41789`. **Revoke browser connections** rotates the secret and requires all browsers to pair again. A copied secret uses the clipboard, whose history/cloud-sync settings are controlled by Windows.

The popup shows the connection state, pending transfers and destination project. **Use desktop project** changes the destination for new captures; queued captures retain their original project. Pairing, worker startup and connection recovery immediately resume ready items. Retry timers and a durable alarm retain offline work. In the desktop, **Raw captures** shows received text before the extraction timer creates any memories. The browser status strip distinguishes receiving, paused, unpaired and unavailable states.

The 64px owl has cursor-following eyes, blinks, writing and inspecting poses, drag/keyboard positioning and reduced-motion support. **Never on this site** persists until explicitly allowed. In addition, 22 entertainment/social domains are immutable hard blocks: YouTube, youtu.be, Netflix, Prime Video, Disney+, Hotstar, Hulu, Twitch, Spotify, TikTok, Instagram, Facebook, X/Twitter, Reddit, Snapchat, Pinterest, Vimeo, Dailymotion, Kick, SoundCloud and Discord. They cannot be restored with an Allow preference; content scripts do not initialize there, queued legacy items are purged, and the desktop API rejects their URLs.

- **No-selection Remember:** on an AI site it captures the latest completed user/assistant turn; elsewhere it captures the page title, URL and up to 6,000 characters of sanitized visible text. Forms, editable/hidden elements and extension UI are excluded. The browser acknowledges only after its local outbox write succeeds. Queue limit: 100 items, 2,000,000 total characters, 200,000 per item.
- **Automatic AI turns:** on ChatGPT, Claude and DeepSeek, the user's prompt is durably staged in the browser immediately on a detected send. A completed assistant reply replaces that staged item with one combined turn. If no reply arrives, the prompt becomes a ready prompt-only capture after 12 minutes. Existing history is seeded and not replayed. Automatic capture does not depend on an importance-model call, so generic or failed-model judgments cannot silently discard raw source. Live site layouts remain experimental and can still cause a missed detection.
- **Understand this page:** an explicit action, separate from opening the owl. Sends URL, title, up to 4,000 selection characters and 6,000 visible-text characters. Forms, editable regions, hidden elements and the companion itself are excluded. No screenshot, video-frame or pixel inspection. Page awareness does not save a memory. Local fallback describes only the page title.

The browser stores its pairing token and pending captures in the local browser profile. Content scripts receive safe preferences and queue counts; only trusted extension contexts can read the token and raw queue. This does not protect against someone who controls your Windows account or browser profile.

## Captured data and storage

The default database is `%USERPROFILE%\.owlthread\owlthread.db`. Override with `--db-path PATH` or `OWLTHREAD_DB_PATH`. It contains source text, source metadata, project names/roots, summaries, timestamps, extraction progress, dedup receipts, lineage and settings. Raw processed captures are retained for audit; there is no automatic retention purge.

When strict site isolation is explicitly disabled and clipboard capture is enabled, the watcher reads changed plain text longer than 20 characters, excludes OwlThread's own copied primers/pairing secrets and saves into the active project. It advances its fingerprint even while paused, so paused text is not captured later as stale data. It cannot identify which application copied text and is not a credential detector. IDE connectors read selected local chat-store records and workspace metadata; unknown global chats go to an Unassigned connector project. They do not scan all source files. Explicit CLI capture stores stdout/stderr and command arguments; do not put secrets in captured command arguments. Terminal transcript retention is capped at 2 MB while remaining output still streams.

No telemetry, cloud sync, screenshots, microphone input, keystroke text logging or general browsing-history import is implemented. Shortcut handling observes only key events needed for the shortcut. Stored memory text is **not encrypted at rest**. Windows protects provider and local-API secrets using user-scoped DPAPI; other operating systems currently use plaintext settings with owner-only database permissions. Read [SECURITY.md](SECURITY.md).

## Projects, extraction and search

The four quadrants are **technical_architecture**, **business_rules**, **settled_decisions** and **open_questions**. They describe kinds of knowledge, not urgency.

Every capture is saved to SQLite before extraction. A running engine extracts every 60 seconds; `done` extracts immediately, including captures created by other processes. Extraction operates in bounded slices with progress checkpoints. Failed configured-model calls, invalid JSON or unsupported decisions leave the capture pending for retry. Explicit Fallback mode uses narrow local rules; it does not silently stand in for a failed extraction provider. Review pending reasons and retry from the desktop.

ADD creates a memory; NOOP leaves it unchanged. UPDATE refines a fact; SUPERSEDE replaces a conflicting fact. Both version the fact, keep the predecessor and record lineage in one transaction. Targets must be active and in the same project and quadrant. The local rules only add facts; automatic conflict inference requires a configured model or an explicit MCP replacement. Exact/normalized duplicates are suppressed; semantic equivalence is not guaranteed.

Search uses SQLite FTS5 **BM25** over both canonical memories and raw capture text, with English stemming, quoted phrases, project/quadrant filters, active-only defaults and a recency multiplier limited to 5%. Primer retrieval fans out across all four quadrants plus raw captures, deduplicates results and packs a hard character budget. Raw evidence is cited as `[C#id]`; canonical memory uses `[#id]`. Exact repeated requests reuse a persistent result cache until the matched evidence or model/prompt configuration changes. There is no vector/synonym search. See [architecture](docs/ARCHITECTURE.md).

Primers default to the active project in the desktop, CLI, HTTP and MCP. History is opt-in where supported. Low-level Python search without a project filter and the CLI `entries` listing can span projects. `done` flushes all projects. Status totals and MCP project listings describe the whole local database.

## Commands

| Command | Result |
| --- | --- |
| `owlthread app` | Desktop and local service |
| `owlthread start` | Tray, service and shortcut |
| `owlthread start --headless` | Service until Ctrl+C |
| `owlthread primer "fix database locking"` | Print and copy a cited brief |
| `owlthread primer --project-id 2 "review constraints"` | Explicit project brief |
| `owlthread test-capture --project Demo "Decision: Use SQLite WAL"` | Durable raw capture |
| `owlthread done` | Extract backlog; reports errors and retains failed captures |
| `owlthread run --project Demo -- python -u script.py` | Stream and capture bounded command output |
| `owlthread git-capture --repo . --enable --file src/app.py` | Opt in and capture last commit metadata plus selected tracked diff |
| `owlthread entries`, `projects`, `status` | Inspect local state |
| `owlthread mcp` | MCP stdio service |

Git capture is explicit on every invocation; it never watches the repository. The first invocation needs `--enable`; `--disable` revokes the project opt-in without capturing. It excludes ignored files (including tracked ignored paths), sensitive filename patterns, possible credential content, binary/oversized files and paths escaping the repository. Select at most 20 files; each diff is at most 64 KiB. `--exclude GLOB` adds a persisted project exclusion list. No full-file automatic scan or commit creation occurs. Filename/content filters cannot guarantee secret detection. The CLI wrapper does not allocate a PTY, so interactive terminal programs can behave differently.

## Providers

Desktop Settings supports Fallback, local Ollama, OpenAI, Anthropic, Gemini, Groq and a custom OpenAI-compatible endpoint. Enter a model available in your account, save and use **Test connection**. Model defaults are editable examples, not a current availability guarantee. Custom remote endpoints require HTTPS; redirects are refused. A local HTTP endpoint is permitted only at loopback. A remote Ollama/custom endpoint is remote processing despite its provider label.

A selected remote provider receives extraction slices and relevant summaries, task text and retrieved memory excerpts, and explicitly requested browser awareness/importance data. Provider billing and retention rules apply. Provider API keys remain in desktop settings. No provider key is sent to the browser. Connection tests return success only for an actual successful response. Primers may fall back to clearly labeled local synthesis; extraction errors retain source for retry. Generated briefs must fit 500 words and cite supplied memory IDs; those checks do not prove factual correctness.

## MCP setup

Point your MCP client's stdio configuration at the extracted console executable, using your real absolute path:

```json
{"mcpServers":{"owlthread":{"command":"C:\\Tools\\OwlThread\\owlthread-cli.exe","args":["mcp"]}}}
```

Or use the source environment's `python.exe` with arguments `-m`, `owlthread`, `mcp`. Add `--db-path` before `mcp` for a separate store. Memory tools are `search_memory`, `record_decision`, `get_quadrant`, `generate_primer`, and `get_memory_stats`. Integration tools are `list_integrations`, `get_integration_status`, `configure_integration`, `test_integration_connection`, and `sync_integration_context`. Configure Cloudflare/GitHub credentials locally in desktop Connect first; MCP never accepts or returns provider tokens. A context sync saves provider snapshots into the selected project's raw capture store, making them searchable and available to primers. Explicit recording is a privileged client action. Configure only trusted local clients. stdout carries MCP messages; diagnostics go to stderr. Calling `generate_primer` copies the brief when clipboard access is available.

## Integration catalog and access boundary

The Connect view and MCP catalog expose 29 definitions: Cloudflare, GitHub, Gmail, Google Calendar/Drive, Dropbox, Box, Airtable, Asana, ClickUp, Trello, Figma, Todoist, TickTick, Granola, Fathom, Plaud, Spotify, Apple Music, SciSpace, Consensus, Runway, Apollo.io, Maersk, CoinMarketCap, CoinGecko, Alpaca, Interactive Brokers and Binance. Every definition starts disabled and unconnected. For Cloudflare/GitHub, open **Connect → Sign in**, finish browser approval, choose a discovered account/public repository, then import. GitHub shows a short device code to enter in the browser. Cloudflare uses its official MCP service; GitHub uses OwlThread's registered public client. Expiring credentials renew locally. Manual token setup remains under **Advanced**, including private GitHub repositories and Cloudflare DNS zone selection. There is no separate plugin installation. Successful provider checks are cached for 15 minutes and invalidated when credentials or grants change. Other services expose local permission definitions only. Admin, destructive and trading scopes cannot be granted through OwlThread MCP. These built-in clients execute no write/deploy/delete operations, even if the broader catalog defines write scopes. Read [connector setup](docs/CONNECTORS.md) for resources, limits and evidence boundaries.

## Backup, restore and migration

Quit all OwlThread desktop, tray, CLI and MCP processes before copying the database. Preserve any `-wal` and `-shm` sidecars if present; do not copy a running database with ordinary file copying. For online backups use SQLite's backup API. Keep a backup before upgrading: migration is additive, introduces FTS5 and capture status, and protects existing Windows secret settings. Migration can take time on large stores. There is no automatic downgrade migration.

To restore, stop all instances and restore the saved database and accompanying sidecars as one consistent set. DPAPI secrets require the original Windows user protection context; after moving to another account/machine, clear/re-enter provider credentials and pair again. Do not edit the encrypted values manually. A full backup includes sensitive raw text; protect it accordingly.

To uninstall, stop the app, remove the unpacked browser extension and its local queue, then remove the extracted app folder. Delete `%USERPROFILE%\.owlthread` only if you intend to erase all local memory. This does not erase existing backups or Windows clipboard history.

## Troubleshooting

- **Desktop offline/unpaired:** start one instance, pair in the popup, and verify port 41789. Use the popup's connection reason; unpaired and revoked authorization are separate from an offline app. The browser uses this fixed port; alternate desktop ports are for CLI/tests.
- **Browser saved data seems missing:** check the popup destination project, switch the desktop to that project and open Raw captures. Received text appears before extraction creates memories. Paused capture keeps the browser queue pending. A staged AI prompt waits for its completed reply, or becomes prompt-only after 12 minutes.
- **Port occupied:** open or quit the existing app. The second instance reports the conflict instead of silently starting another capture service.
- **Saved model key unavailable:** the desktop opens with an empty model key and asks you to enter it again in Settings. The old encrypted value stays in the database until you save a replacement. If a saved browser token cannot be unlocked, pair the extension again.
- **No extraction:** inspect pending status, verify the configured provider, or explicitly select Fallback. Speculation, generic explanations and raw code usually produce no memory.
- **No search result:** use a phrase present in the memory, check the project and whether the fact is archived/superseded. Synonyms are not expanded.
- **Clipboard unavailable/shortcut conflict:** use the displayed brief and desktop/tray Primer control. Inspect other applications' bindings.
- **IDE missing data:** the adapters are experimental and bounded to 2 MB session records. Use manual or CLI capture and report a redacted schema fixture.
- **Settings source changes:** restart after changing clipboard/IDE switches. Provider changes apply on the next request.

## Development and releases

Read [CONTRIBUTING.md](CONTRIBUTING.md), [architecture](docs/ARCHITECTURE.md), [security](SECURITY.md) and [release procedure](docs/RELEASE.md). `continue/` is an unmodified reference submodule, not product runtime. Previously removed mem0 reference gitlinks remain removed; no reference-project code is bundled.

Run Python tests with `python -m unittest discover -s tests -v`. In `extension/`, run `npm ci` and `npm test`; `npm run test:browser` exercises a real isolated browser with synthetic pages. `node tests/api-browser.cjs` exercises the real isolated Python API (Windows source environment expected). Generated JavaScript is checked against TypeScript before a release. Versions come from `pyproject.toml`, synchronized with `tools/sync_version.py`. Release artifacts are local and have not been uploaded or published.
