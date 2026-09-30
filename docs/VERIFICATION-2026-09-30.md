# OwlThread 1.6.0 verification — 2026-09-30

The Chrome transfer path, desktop visibility and context integrations were audited together. Existing pending extraction/provider edits were preserved. No commit, push, cloud deployment or extension-store submission was performed.

## Transfer diagnosis and fixes

The default local database was inspected read-only. It contained no authorized browser origins and no browser-extension captures; its active project was `OwlThread-V2`. This is a snapshot of that database, not proof about an alternate database or Chrome profile. No OwlThread process was detected at that check. Pairing must therefore be completed for that store, and the extension destination must match the desktop project to see its captures.

Reproduced code defects were independent of that setup state: pairing/startup/recovery did not immediately resume queued work; a capture added during an in-flight send could wait until the next alarm; and popup errors collapsed missing/rejected pairing into an offline message. The first new-chat URL assignment could also lose a staged reply. The extension now resumes ready work immediately, drains in-flight additions, retains durable alarm retries and preserves staged turns across supported new-chat transitions. Project adoption is explicit and queued items retain their original project.

The desktop previously showed extracted memories while raw captures waited for the extraction timer. Raw captures now appear independently, with receive timestamps, source/page details, pending/failed state and original text. Counts are scoped to the selected project. Incoming work preserves capture/settings/connection drafts and refreshes search. Minimum-size footer clipping and animation/callback cleanup were corrected.

## Included context clients

Cloudflare and GitHub now have built-in GET-only clients, desktop-local Windows-protected credentials, exact read scopes, explicit resource/project setup, test/import/disconnect controls and two MCP test/sync tools. Imported raw snapshots are immediately available to raw search and primers. Grants, credentials and project state are checked before saving; captures, dedup receipts and sync state commit atomically. Responses and record sizes are bounded, redirects refused and provider errors omit credentials. Other catalog definitions remain unconnected.

No Cloudflare/GitHub account token was supplied or used during verification. Provider fixtures establish request/response and safety behavior, not live account authorization. Use desktop **Test access** after setup to confirm your account. See [connector setup](CONNECTORS.md).

## Measured checks

| Check | Result |
| --- | --- |
| Initial Python baseline | 169 passed |
| Final Python suite | 203 passed, 0 failed; 32.489 seconds |
| Extension behavior | 28 passed |
| Real Chrome → authenticated local API → SQLite | 23 checks passed, isolated source service |
| Isolated Chrome and Brave extension UI | Passed, synthetic pages; popup fits 360 × 600 |
| GUI widget checks | 9 passed, included in Python total |
| Integration checks | 36 passed, included in Python total; 23 new connector/transport methods |
| Source app/tray startup | Passed; desktop visible, authenticated API ready; about 1.5 seconds |
| Built executable CLI/clipboard/MCP | Passed, including exact ten-tool set and bundled Cloudflare availability |
| Built app/tray/default startup | Passed; visible app/default, hidden tray; authenticated API; about 1.5 seconds |
| Production inputs | All 68 hashes match the final build; generated JS matches TypeScript |
| Existing build environment | Pinned environment reused; dependency consistency check passed |
| Wheel and source archive | Both built successfully |
| Fresh ZIP extraction | 291 checks passed, including extracted executable CLI/MCP flow |
| Offline wheel install/source rebuild | 11 checks passed; installed package imports independently of checkout; pinned dependencies reused |
| Whitespace | Passed with Windows CRLF handling |

Counts overlap and must not be added as independent coverage. The 1.6.0 build was rebuilt after the final UI and connector edits. Production-input hashes and the dirty checkout state are recorded in build-provenance.json; it is a local build from pending changes.

Eight screenshots exercise Feed, Raw captures, Connect and Settings at 1180 × 800 and 920 × 650 with synthetic data. They were rendered by real Tk and visually inspected; the minimum-size footer and scroll viewport are also regression-tested. Images are under `artifacts/audit-2026-09-30/` in the source checkout. This is scripted rendering and widget use, not physical-user acceptance.

## Local outputs and remaining evidence limits

The Windows portable ZIP, Chrome/Brave extension ZIP, wheel, source archive and checksums are under `artifacts/release/1.6.0/`. The archive verifier passed CRCs, safe extraction paths, checksums, bundled extension bytes, provenance/version and the extracted executable's CLI/MCP flow. Runtime logs are saved under `artifacts/current-audit-*.log` in the source checkout. The offline package check reused the pinned build runtime, verified independent wheel imports and rebuilt a wheel from the source archive. An initial attempt to reuse the system runtime exposed an out-of-range MCP 2.1.1 dependency; verification was repeated successfully using the release's pinned MCP 1.30.0 environment. No clean dependency-download claim is made.

The normal user database and Chrome profile were not changed by tests. Reload/install the updated extension, refresh its target tabs, pair it to the running desktop and choose the matching project. Use **Raw captures** to distinguish a successful receive from extraction.

Signed-in ChatGPT/Claude/DeepSeek pages, live paid model/provider accounts, current private IDE chat formats and the global shortcut outside the app remain unverified. No clean dependency download was performed in this run; build dependencies were reused. The build is unsigned and local. These limits do not invalidate the exercised queue, local API, persistence, GUI and packaged-runtime checks.
