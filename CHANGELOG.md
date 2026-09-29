# Changelog

## Unreleased

- Replace selection-only browser capture with no-selection current-turn/page capture.
- Stage new ChatGPT, Claude and DeepSeek user prompts durably at send time; merge completed replies under the same idempotency key and retain offline work.
- Enforce 22 immutable blocked domains at manifest, content, worker queue and desktop API boundaries; enable strict site isolation so origin-blind clipboard monitoring stays off by default.
- Index raw captures with FTS5, diversify retrieval across all four quadrants, enforce a context budget and cache repeated primers by evidence revision to reduce model tokens.
- Add an honest 29-service integration permission catalog, including Cloudflare, with disabled/unconnected defaults and MCP denial of admin, destructive and trading grants.
- Support both MCP Python 1.x and 2.x server imports and test real stdio transport.

## 1.5.0 — 2026-09-14 (local release candidate)

- Authenticate the loopback API, pair exact extension origins and protect Windows secrets using DPAPI.
- Restrict browser secrets/raw queues to trusted extension contexts; validate settings, URLs, projects, sizes and request rates.
- Persist project attribution in manual queues and hold legacy notes for explicit assignment; automatic replies remain unqueued offline.
- Consolidate atomic extraction/rebase with source evidence, retry status and versioned lineage. Retire duplicate observers and the unused in-memory buffer.
- Implement SQLite FTS5 BM25 with bounded recency weighting and active/project filters; scope default primers to the active project.
- Add narrow extraction evaluation, explicit opt-in selected Git diffs and bounded CLI retention. Map IDE workspaces separately from active desktop projects.
- Move desktop I/O to workers; add pairing, pending-capture review, source opt-in switches and responsive action handling.
- Preserve the existing cozy owl artwork/motion and fix popup fit and manual selection fallback.
- Validate primer citation IDs and length; preserve local synthesis on generation failure while keeping failed extraction pending.
- Align package versions, resolve the extension asset graph, pin a clean Windows build environment and record build provenance.

See docs/VERIFICATION.md for measured coverage. No paid-provider or current signed-in AI-site integration is certified by this release.
