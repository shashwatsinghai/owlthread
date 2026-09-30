# OwlThread browser extension 1.6.0

Load the folder containing manifest.json in Chrome or Brave using Developer mode → Load unpacked. Compiled JavaScript is included. Pair with the desktop's copied secret in popup Preferences & connection → Connection settings, then choose a capture project. Never put the secret into a website. Provider keys remain in the desktop.

The 64px cozy owl preserves its writing, magnifying-glass, blink, cursor-following and reduced-motion behavior. Opening the owl sends no page text. Remember saves the latest completed AI turn or a sanitized visible-page snapshot without requiring a selection. Understand this page remains a separate explicit action. Forms, editable regions and hidden text are excluded; this is DOM text awareness, not visual understanding.

All captures persist in the browser before acknowledgement, with a 100-item/2-million-character queue limit. Each item retains its capture-time project. Legacy unassigned notes stay held for review. Hard-blocked legacy items are purged; ordinary user-blocked items stay held. Raw queue and pairing token are restricted to trusted extension contexts, but remain in the browser profile.

Pairing, opening the popup, a successful connection check, browser startup and service-worker wake all resume delivery automatically. Captures added during an in-flight send drain in the same cycle. A closed desktop triggers short retries while the worker stays awake, with a persistent one-minute alarm as the fallback when Chrome suspends it. Popup status distinguishes an unpaired browser, rejected pairing, an unreachable desktop and a server error. Delivered raw captures and extracted memories are separate stages; the popup reports the last delivery project and time. Use desktop project explicitly adopts the app's selected project for new captures; existing queued items keep their original project.

Automatic capture on ChatGPT, Claude and DeepSeek stages the user's prompt immediately on send, then joins the completed reply to the same durable queue item. A prompt with no detected completion becomes prompt-only after 12 minutes. It does not use a model importance gate and works while the desktop is offline. Existing history is not replayed. Live AI-site layouts are experimental; there is no browser-history collection or cross-device sync.

The first turn can follow a supported site's new-chat URL assignment without losing its reply. Switching between existing chats still abandons reply attachment, and delayed acknowledgements cannot clear a newer pending turn.

YouTube/youtu.be, Netflix, Prime Video, Disney+, Hotstar, Hulu, Twitch, Spotify, TikTok, Instagram, Facebook, X/Twitter, Reddit, Snapchat, Pinterest, Vimeo, Dailymotion, Kick, SoundCloud and Discord are immutable hard blocks. Content scripts do not initialize there and a saved Allow value cannot override the boundary.

See help.html for setup, site choices and the optional prompts/memory-filter.txt template. It does not overwrite desktop prompts.

Run npm ci, then npm test. Run npm run test:browser for installed isolated Chrome/Brave checks with synthetic pages and mocked desktop transport. Run node tests/api-browser.cjs for installed Chrome against an isolated real Python API (expects the source .venv on Windows). OWLTHREAD_TEST_BROWSER selects a browser executable. These tests never write to the user's normal database and do not certify paid credentials or signed-in AI-site flows.

TypeScript owns behavior; JavaScript is generated. The release verifier compares generated output and resolves all manifest, popup, helper and artwork dependencies. See the root README and docs/VERIFICATION.md for full coverage and limitations.
