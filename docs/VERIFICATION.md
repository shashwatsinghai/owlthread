# Verification report — 2026-09-14

## 2026-09-23 launcher follow-up

`run.bat` now opens the visible desktop, and the packaged executable opens it when started without arguments. Tray mode remains available through `start`. Desktop and tray startup passed against isolated databases; the desktop window was confirmed visible, and the authenticated local API responded. Unused CLI and capture-source imports now load only when needed. A local Windows build and the 1.5.0 ZIPs, wheel and source archive were refreshed from current sources.

Current automated checks passed: 164 Python tests, 21 extension tests, installed Chrome and Brave browser smoke tests, 18 real browser-to-API-to-SQLite checks, packaged CLI/MCP smoke, and 289 checks on freshly extracted archives. An offline wheel install, capture/extraction and extracted source archive rebuild also passed. A fresh install of all pinned dependencies could not be repeated in this sandbox because PyPI access was denied; an elevated retry could not read the workspace wheel. The offline wheel check reused system runtime dependencies, so it does not replace a clean dependency-install check. Native visual interaction and the global shortcut outside the app remain unverified.

An existing user database exposed a stricter `settings.updated_at NOT NULL` schema. Browser-token creation and extension pairing now write timestamps. A copied user database also contained a model key that could not be decrypted in the current Windows context; the desktop now opens with that key unavailable, keeps the stored ciphertext until the user replaces it, and shows a Settings notice. An unreadable browser token is regenerated and prior pairings are cleared. Desktop startup, token creation and pairing passed on a temporary copy of that database; the original was not changed during verification.

## Executive result

**Core completion estimate: 88%. Public-release readiness: 80%. Broad public release is not recommended yet.** The local 1.5.0 release candidate is suitable for further controlled evaluation. These are transparent engineering rubric scores, not measured user-success probabilities.

Core scoring awards 1 for a coherently implemented and exercised surface, 0.5 for partial evidence, and 0 for missing work. The 20 areas are storage, projects, authenticated API, secret handling, clipboard, CLI, IDE, Git, browser queue, AI-site observers, canonical rebase, extraction quality, search, primer, providers, MCP, desktop views, global shortcut, companion and page awareness. IDE, AI-site observers, extraction quality, providers and the shortcut receive 0.5; the other 15 receive 1. Total 17.5/20 = 87.5%, rounded to 88%.

Release scoring uses 20 equal gates. Preservation, runtime ownership, Python/extension tests, local API security regression, current-source build, version consistency, asset completeness, fresh ZIP extraction, fresh Python install, MCP process, native clipboard, GUI process startup, tray process startup, Chrome integration, Brave integration and accurate docs pass (16). Live shortcut outside the app, native visual interaction, signed-in AI-site compatibility and live provider/current IDE format certification remain open (4). Total 16/20 = 80%. Scores do not hide those open gates behind passing fixture tests.

## Starting state and preservation

The starting branch was master at 30ef180, with 99 status entries including extensive uncommitted Python/extension work and already-deleted mem0 reference gitlinks. Baseline: 104 Python tests passed; 17 extension tests passed. Binary worktree/index patches and the initial status are in artifacts/audit-2026-09-14. Retired buffer/rebase/observer source copies are preserved there. The existing artwork, motion, desktop, provider adapters and prior reliability work were extended. No reset, commit, force push, reference-project edits or release upload occurred.

## Completed work and evidence

| Area | Change and important files | Evidence |
| --- | --- | --- |
| Local API security | security.py, capture/server.py: bearer pairing, exact origins/Host, revocation, DPAPI secrets, bounds/rate/concurrency limits | 15 security methods with real loopback requests; real browser/API integration |
| Canonical memory | db/database.py, extraction/pipeline.py, rebase.py: same-project/quadrant versioned actions and atomic capture checkpoint; old engine/buffer retired | 11 rebase methods, 16 reliability methods, restart/process and rollback cases |
| Extraction quality | extractor.py: conservative explicit facts; strict source evidence and model-output validation; pending retry status | 30-case local corpus: TP 12, TN 18, FP 0, FN 0; precision 1.0, FPR 0.0 on this corpus only |
| Search and primer | primer/search.py FTS5 BM25, bounded recency; active-project defaults; generator citation/length guard | 6 BM25 methods plus existing search/primer suites; 2,000-record search fixture |
| Capture | Git explicit opt-in/disable and selected exclusions; CLI retention cap; workspace mapping and source opt-in | 5 real temporary-Git tests, 3 CLI, 3 IDE fixture and 2 clipboard tests |
| Browser queue and privacy | background.ts, policy.ts: capture-time project, legacy review, trusted storage, bounded safe settings, private-field exclusions | 20 extension tests; 16 assertions in the installed Chrome → real HTTP → SQLite flow |
| Companion and observers | Preserved existing art/gestures; fixed compact popup and manual selection fallback | Chrome and Brave installed visual suites; zero page errors; observer DOM fixtures |
| Desktop | gui/app.py, primer/ui.py, tray.py: worker I/O, stale-view checks, pairing, pending status, source switches | 2 real Tk tests including a blocked-worker responsiveness test; isolated packaged GUI and tray process startup |
| Providers and MCP | llm.py adapters retained with request validation; shared canonical MCP persistence; truthful duplicate metadata | 9 adapter fixture tests; 5 MCP tool tests; real stdio tests and packaged smoke |
| Release and docs | version 1.5.0, dependency graph, generated-JS comparison, clean dependency lock, build provenance, licensing and complete ZIPs | 2 source packaging tests, clean PyInstaller build, package and fresh-install suites; SHA256SUMS.txt |

## Exact test results

Counts below overlap where a subsystem is part of the Python total; do not add them together as independent coverage.

| Suite | Result | Evidence file under artifacts/audit-2026-09-14 |
| --- | --- | --- |
| Baseline Python | 104 passed | python-baseline.txt |
| Baseline extension | 17 passed | extension-baseline.txt |
| Final Python | 140 passed, 0 failed, 0 skipped; 19.852 seconds | python-final3.txt |
| Final extension | 20 passed, 0 failed, 0 skipped | extension-final3.txt |
| Security | 15 methods, included in Python total | test_security.py / python-final3.txt |
| MCP | 5 tool methods + 1 real stdio test, included in Python total; also packaged stdio smoke | test_mcp_server.py, test_process_integration.py, package-built.txt, archives-final.txt |
| Browser | 2 installed visual suites (Chrome, Brave) plus 1 real Chrome/API suite with 16 assertions | browser-chrome-final.txt, browser-brave.txt, browser-api-final2.txt |
| Packaging | 2 Python asset/version methods; 1 built-executable integration suite; 1 fresh-archive suite; 1 fresh-Python install/rebuild suite | package-built.txt, archives-final.txt, python-install-final.txt |
| Native process startup | 2 modes passed: desktop and tray, each with authenticated API and opt-in sources off | desktop-startup.txt |
| Native clipboard | Successful real copy in built/extracted package smoke | package-built.txt, archives-final.txt |
| Hands-on native UI/shortcut | 0 completed manual interaction flows; blocked by window-identity error in UI tool | Described below |
| Dependencies | No broken requirements in clean environment | pip-check.txt |
| Repository whitespace | git diff --check passed | diff-check.txt |

Python 3.14.7, Windows 11 build 26200, Chrome 153.0.8010.36, Brave 153.1.95.101 and PyInstaller 6.22.0 were used. The clean Windows environment has 45 pinned runtime/build packages. Generated JavaScript matches TypeScript; the production-input provenance contains 62 hashes. The Chrome/Brave visual suites install and reload the real unpacked extension, but serve synthetic pages and mock desktop transport. Only the separate real API suite proves integrated pairing and persistence.

## Incorrect or contradictory areas corrected

- The prior unauthenticated local routes and broad CORS were incompatible with private project memory.
- Multiple rebase/buffer implementations disagreed about whether updates edited in place or created a successor.
- Keyword overlap was described as BM25. Retrieval now calls SQLite FTS5 BM25.
- Generic keywords and speculative text could be promoted to facts; source and commitment checks are now conservative.
- Browser queue items could inherit the wrong project at sync time; capture-time attribution is now persisted.
- Content-script storage access exposed the same storage area as secrets/raw queued notes.
- Configured extraction failures silently resembled successful local fallback; failed captures now remain pending.
- The popup grew beyond its usable height after connection controls were added; expandable preferences fixed it.
- A settings message listener changed unsupported-site response behavior and prevented manual selection fallback; the fallback now handles empty replies as well as errors.
- The old bundle omitted policy.js, prompts and current artwork while using inconsistent Python/extension version numbers.
- Marketing claimed all data never left the machine and described quadrants as urgency. Documentation now explains remote processing and the actual categories.
- The initial clean build imported the optional MCP CLI and failed without typer. The bundle now excludes that unrelated CLI while including the MCP runtime.

## Remaining partial work

| Area | Current status and missing portion | Risk and next step |
| --- | --- | --- |
| Extraction quality | Strict validated structure, evidence snippets and 30-case regression corpus; no representative independently labeled production corpus | False facts or omissions remain possible. Expand multilingual/long-dialogue adversarial evaluation and compare providers with explicit account approval. |
| IDE connectors | Bounded parsers and workspace fixtures; installed Cursor/VS Code versions located, live private chat stores not certified | Storage format changes may miss or misattribute content. Test sanitized fixtures exported from the exact current versions; remain opt-in/experimental. |
| AI-site observers | Send/stream/navigation DOM fixtures and manual fallback; no signed-in ChatGPT/Claude/DeepSeek end-to-end run | A DOM change may skip a turn. Exercise one real new conversation per service and navigation/reload before elevating support claims. |
| Provider integration | Nine controlled adapter/error tests; no real paid credentials or Ollama model used | Account/model compatibility and latency are unverified. Use desktop Test connection with a chosen account and a non-sensitive task. |
| Windows UI/shortcut | Real Tk tests, clipboard, GUI/tray startup; native UI tool repeatedly rejected the sample window with an identity mismatch reporting the same owner | No visual review of Tk views or physical shortcut verification outside the app. Perform a normal-session manual acceptance run, including project switching, settings, pending retry, tray quit and duplicate shortcut prevention. |
| Operational release | Unsigned portable build and source packages, local only | Signing, distribution, update policy, migration backup UX and broader installation-matrix coverage remain future release work. |
| Semantic search and retention | BM25 only; raw captures retained indefinitely | Synonym-only matches can fail and stores grow. Do not advertise vectors; design explicit retention/export/deletion controls before broad sensitive use. |

## Security assessment

The original anonymous memory API was a critical boundary failure and is now closed in the exercised attack cases. No known critical API bypass remains in the audited paths. This does not establish that the application has no undiscovered critical defects.

High-impact residual risks are raw unencrypted memory/queues, opted-in sensitive capture and explicitly configured remote-model disclosure. Medium risks include semantic hallucination/prompt injection, changing IDE/site formats, authorized-client misuse and local denial of service. Low risks include unsigned binaries, limited retention tooling and non-Windows secret protection. See SECURITY.md for the full threat model and platform references.

## Release contents and limitations

The authoritative local release directory is artifacts/release/1.5.0. It contains OwlThread-Windows-1.5.0.zip, OwlThread-Chrome-Brave-1.5.0.zip, owlthread-1.5.0-py3-none-any.whl, owlthread-1.5.0.tar.gz and SHA256SUMS.txt. Read the checksum file for final digests; it is regenerated whenever artifacts change. Older unversioned outputs are preserved and are not the current release.

The Windows ZIP includes GUI/console executables, runtime dependencies, compiled extension, setup batches, project documentation, build provenance and third-party notices/licenses. The extension ZIP contains every resolved runtime dependency. The wheel is the Python package; the sdist includes extension sources/assets, tests and tools. No cloud service, GitHub release, store listing or signed installer was published.
