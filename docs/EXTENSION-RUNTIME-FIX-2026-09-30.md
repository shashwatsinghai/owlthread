# Extension runtime repair — 2026-09-30

Chrome reported `Cannot read properties of undefined (reading 'onMessage')` at `policy.js:92`, plus the equivalent `getURL` error, on an existing Freelancer tab. The runtime was absent when that code accessed it. Extension reload/disable can leave old page code without working extension APIs; the normal user profile was not inspected or changed to determine which action triggered this report.

The repair checks the runtime before installing content observers or companion controls, guards asset URLs and message sends, and reports a refresh instruction when settings cannot be reached. It keeps original message event handles for cleanup, tolerates invalidated handles, avoids duplicate subscriptions, and retires previous subscriptions before policy reinjection. Disposed observers stop capturing, and delayed settings replies cannot restore removed controls.

The separate extension hotfix is `artifacts/extension-hotfix/1.6.0/OwlThread-Chrome-Brave-1.6.0-runtime-fix.zip`. Its version remains 1.6.0 to match the desktop. It has separate checksums and extension provenance. Existing full-release archives and their build provenance retain their original bytes; they contain the previous extension code.

## Apply the repair

If Chrome loads this checkout's `extension` folder, open `chrome://extensions`, find OwlThread, click **Reload**, and refresh the affected website tabs. Reloading the extension does not execute replacement code in every old page immediately.

For an unpacked extension installed from a ZIP, extract the hotfix and copy the contents of `OwlThread-extension` into the same installed folder, replacing its runtime files. Then click **Reload** and refresh the affected tabs. Keeping the same extension folder preserves its extension identity, pairing and queued captures. Use the extension popup to check the desktop connection and destination project.

## Verification

All 40 extension tests pass. The nine lifecycle regressions fail against the previous implementation and pass against the repair. They cover absent and throwing runtime APIs, duplicate registration, full reinjection, invalidated listener removal, failed startup settings, capture attempts after runtime loss, and delayed settings responses. The real Chrome smoke includes an already open tab surviving an extension reload, repeated reinjection and a subsequent successful Remember action, with no page errors.

The authenticated Chrome → Python API → SQLite check passes 23 assertions; extension asset/version checks pass two tests. Tests use isolated browser profiles and synthetic pages. The reported signed-in Freelancer tab and the normal Chrome profile remain outside these automated checks. Logs are under `artifacts/extension-runtime-fix-*` and `artifacts/runtime-fix-*`.
