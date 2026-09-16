# Changelog

## Unreleased

- Fix profiles failing to open from Finder, Spotlight, or the Dock once any other instance was running. Electron takes its data directory only from `--user-data-dir`, which those launches cannot pass, so a profile fell back to the shared default directory, reported `Opening in existing browser session.` and exited. Each profile app now carries a launcher as its main executable that supplies its own settings however it is started.
- Fix most profiles exiting when several were launched in quick succession, which had the same cause.
- Treat a profile application without that launcher as stale so existing profiles are rebuilt on the next sync, and add `sync --force` to rebuild regardless of version.

- Add opt-in two-way conversation sharing with `sessions sync/enable/disable/status`, including paginated message history and a 15-second macOS LaunchAgent.
- Back up conversation databases before sharing, retain separate account state, and report schema mismatches and sync failures.
- Restore moved session paths with `repair <name> [--from /old/profile/home]`.
- Automatically recover the legacy `.codex-profiles` layout on launch when the conversation index and existing session files establish the moved profile's location.
- Preserve occupied old paths and keep launch working if automatic recovery is unavailable.

## 1.0.0 — 2026-09-16

Initial public release.

- Run multiple Codex desktop accounts concurrently with separate Codex and Electron directories.
- Launch all profiles in sequence with `launch --all`, skipping running apps and reporting failures.
- Create named application copies with ten colored icons and unique bundle identifiers.
- Use APFS copy-on-write cloning with a full-copy fallback.
- Download the official app and verify its signature, OpenAI signing team, and bundle identifier before installation.
- Re-sign profile apps using a detected certificate or ad-hoc signing.
- Sync profile apps after official updates while preserving local profile data.
- Track both app version and build number when checking whether sync is needed.
- Include profile listing, installation diagnostics, and confirmed profile removal.
- Create the user Applications directory when needed and show progress while building profiles.
- Document CLI-only isolated launching, setup, updates, privacy boundaries, signing, and troubleshooting.
- Publish original code and documentation under MIT, with separate artwork notices, regression tests, and macOS CI.
