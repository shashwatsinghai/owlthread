# Contributing

Preserve existing work before editing. Inspect git status and the diff; do not reset another contributor's uncommitted changes. Reference submodules are not OwlThread runtime. Keep generated JavaScript synchronized with TypeScript and avoid adding alternate capture/extraction implementations.

Use Python 3.11+ with Tk support and Node/npm. Create a private virtual environment; pip install -e . and npm ci in extension/. For the audited Windows build, use requirements-windows.lock. Do not commit .env, databases, profiles, credentials, node_modules, virtual environments or release ZIPs.

Run python -m unittest discover -s tests -v from the repository root and npm test from extension/. Browser fixtures are synthetic; never call them live provider evidence. npm run test:browser uses an isolated Chrome/Brave profile. node tests/api-browser.cjs also starts an isolated Python server and never uses the normal database. Preserve stderr diagnostics for MCP and keep protocol stdout clean.

Changes to authentication, project scoping, capture persistence or rebase need adversarial/transactional regression coverage. Reversible visual-only changes need a targeted visual check, not tests that simply copy implementation details. Record exact commands, environment, count and outcome. Test new persistence behavior across a database restart.

Provider tests must use fake keys and controlled transports unless a user explicitly authorizes a live account test. Never attach real captured text to issues. Report security issues privately as described in SECURITY.md.

Version is owned by pyproject.toml. Run tools/sync_version.py, rebuild the extension, verify all tests and follow docs/RELEASE.md. A green mocked suite alone does not justify a production-ready claim.
