# OwlThread 1.7.0 browser sign-in verification

## Implemented behavior

Connect offers Sign in with Cloudflare/GitHub, browser reopening, cancellation, discovered resource choices and explicit import into the project selected at sign-in start. All other integrations show Coming soon with no setup controls. Existing data/grants are preserved. Manual token controls remain under Advanced. Duplicate account names remain independently selectable. Browser authorization runs outside the UI job pool; cancellation and shutdown reject late credential writes.

Cloudflare uses its official remote MCP OAuth server, dynamic public-client registration, PKCE S256, state/issuer validation and a random IPv4 loopback callback. Its execute tool receives only generated, allowlisted GET requests. GitHub uses the OwlThread OAuth app registered by shashwatsinghai, public Client ID `Ov23lipL10mn453vuau8`, Device Flow enabled and token expiration enabled. No Client Secret was generated or bundled. The GitHub browser option requests only `read:user` and discovers public repositories; private repositories retain the fine-grained token option.

Access and refresh tokens are stored in Windows user-protected local credentials and omitted from public status, general settings and captures. Renewal occurs before the import snapshot. Concurrent renewal is serialized; disconnect/reconfiguration rejects stale credential writes. A connection disabled during renewal is rejected before any context request. Resource selection saves its grant/options atomically with the current auth/credential snapshot and binds import to that exact revision. A new login cannot mix its token with an old resource/project. Imports retain transactionality and deduplication.

## Measured checks

| Check | Result |
| --- | --- |
| Python suite on the pinned Windows build environment | 226 tests passed |
| New OAuth tests | 19 passed: real loopback callbacks, wrong state rejection, cancellation, project attribution, both providers' credential redaction, device backoff, denial, renewal, disconnect, disabling during renewal and new-login selection races |
| GUI tests | 13 passed, including Coming soon controls, duplicate account names, preserved drafts/selection and 920 x 650 layout |
| Extension tests | 40 passed |
| Isolated extension browser smoke | Passed; synthetic pages, popup/reinjection/reduced motion and zero page errors |
| Real isolated browser/API | 23 checks passed |
| Cloudflare sign-in compatibility | Live public-client registration, browser approval, callback/token exchange and authenticated MCP account discovery passed; one accessible account returned |
| GitHub registration and signed-in account test | Passed on GitHub: device approval, public `shashwatsinghai/owlthread` discovery and one repository snapshot imported into the isolated project |
| GitHub expiring token renewal | Live refresh succeeded without Client Secret; renewed token imported successfully |
| Built Windows desktop | Visible app/default startup and tray startup passed; authenticated API healthy and fresh capture sources off |
| Built CLI/MCP | Capture, extraction, primer, native clipboard, status and exact ten-tool MCP stdio flow passed |

The provider account checks used temporary isolated databases; they did not configure the user's normal OwlThread database. No credentials were printed. The earlier Cloudflare sign-in/account-discovery success was observed in the browser and tool output. A later, separate context-import/renewal attempt encountered an expired browser authorization and timed out; the current `artifacts/browser-login-cloudflare-live.log` and public-status file record that later failed attempt, not the earlier successful discovery. The user requested stopping further Cloudflare attempts. Account context import and renewal are covered by fixtures but are not certified against the live account. These results do not certify private GitHub repositories, physical-user acceptance, every Windows installation or signed distribution.

Five Connect screenshots at 920 x 650 cover ready and synthetic signed-in states for both providers plus the Coming soon section under `artifacts/browser-login-qa/`. They were rendered by real Tk, visually inspected and have a visible footer with Advanced collapsed. Logs are under `artifacts/browser-login-*.log`.

## Local release

The local 1.7.0 release includes the new browser sign-in runtime and the previously verified extension runtime crash fix. Version mirrors and generated JavaScript are synchronized. Production input hashes are recorded in build provenance. Portable Windows/extension ZIPs, wheel/sdist and checksums are generated under `artifacts/release/1.7.0/`. Packaging integrity and extracted runtime results are recorded in the archive verification log. Source publication, extension-store publication and binary distribution are separate actions.
