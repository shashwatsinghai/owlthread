# Security model — 1.5.0

OwlThread stores sensitive project context. Local storage is not equivalent to complete privacy. There is no claim of zero vulnerabilities or a penetration-test certification.

## Boundaries enforced

- The HTTP listener binds only to 127.0.0.1. Host must exactly match localhost/127.0.0.1 and the listening port. Duplicate Host/Origin/Authorization headers and normal website origins are refused.
- Only GET /health is public, returning app identity and health. Every memory/status/project/capture/primer/extraction route requires a random 256-bit bearer secret. A Chrome extension origin also needs explicit pairing. Pairing itself requires the bearer secret. CORS echoes an authorized origin; it never grants wildcard access.
- Revoke rotates the secret and clears authorized origins. Each request checks current credentials. Content scripts cannot read browser storage secrets: Chrome storage access is restricted to trusted contexts, and the worker exposes only safe preferences/counts.
- Requests have JSON/type/size validation, bounded metadata and query sizes, strict project references, 16 concurrent request slots, 15-second socket timeouts and a global 120 requests/minute limit. DNS-rebinding-style Host attacks, credential-bearing URLs, wrong origins and missing credentials have real HTTP regression coverage.
- Windows DPAPI protects provider/API secrets in settings. Raw notes, prompts, source metadata and summaries remain readable in SQLite. POSIX fallback uses owner-only database permissions; settings there remain plaintext.
- Remote provider endpoints require HTTPS; local HTTP is loopback only. Provider redirects are refused. Browser awareness is explicit and excludes forms/editable/hidden DOM text. The extension has no external messaging API and stores no provider keys.
- Twenty-two entertainment/social domains are hard-blocked in the manifest, content scripts, service worker queue/drain path and desktop URL validation. An Allow preference cannot override them. Strict site isolation is enabled by default and disables the origin-blind clipboard watcher; disabling strict isolation is an explicit privacy tradeoff.
- Integration definitions are permission metadata, not live connections. They start disabled/unconnected, require exact scopes and may be project-scoped. MCP cannot grant admin, destructive or trading scopes. Credentials are not stored by the integration registry.
- Capture/model text is untrusted input. Extraction validates action shape, exact source evidence, targets and same-project/quadrant boundaries. Known injection and credential patterns are rejected; settled decisions require explicit commitment evidence. This is a conservative heuristic defense, not a complete prompt-injection solution. The model has no action-execution tools.

## Residual risks

**Critical:** none identified in the tested API boundary after the changes. This is scoped evidence, not proof of absence.

**High:** enabling a remote model sends selected source context to that endpoint. If strict site isolation is disabled, clipboard capture cannot determine the source application/site and may contain blocked-site text or secrets. IDE/CLI capture has similar content risk. Raw memory and browser queues are unencrypted. Same-user malware or a compromised trusted extension/client can read or change memory. Do not use this candidate for sensitive organizational data without reviewing those assumptions.

**Medium:** automatic model decisions and generated prose can still be wrong or follow sophisticated injected text. Exact snippets/citation IDs do not prove semantic entailment. Experimental IDE/browser layouts may miss or misattribute records. Authentication cannot prevent an already authorized process from modifying data. A local process can exhaust rate limits, and no service-level resource guarantee exists. Windows clipboard history may retain copied secrets/briefs. Provider URLs configured by a trusted desktop user can intentionally target any HTTPS host.

**Low:** binaries are unsigned, no auto-updater is provided, raw captures and dedup receipts have no age-based retention policy, and support for non-Windows secret storage is incomplete. The browser's fixed service port is not configurable in the popup.

## Reporting

Report a suspected vulnerability privately to the project maintainer through a channel you already trust. Do not attach a real database, provider key, pairing secret, browser profile or private chat text to a public issue. Provide a minimal redacted reproduction and affected version. No monitored security mailbox or response-time guarantee is claimed here.

## References

The implementation uses [Windows DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) for user-scoped secret protection and [Chrome storage access levels](https://developer.chrome.com/docs/extensions/reference/api/storage) for trusted-extension storage. These mechanisms have the platform limitations described above.
