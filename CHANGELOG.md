# Changelog

## Unreleased

- Sync sidebar projects and the chats filed under them. Each app keeps its project list and thread assignments in its own `.codex-global-state.json` under app-specific IDs, so synced chats showed up without their projects. Projects are now matched by folder and merged both ways, including renames, removals and moves between projects; an app's file is updated only while that app is closed, because it reads the file once at launch and overwrites it while running.
- Fix `install` downloading the wrong application. The old download link now serves the separate ChatGPT chat app (`com.openai.chat`), which the bundle identifier check rejected, so a fresh install could not succeed. `install` now downloads Codex from `codex-app-prod/Codex.dmg`, the link the Codex app itself uses.

- Stop profiles from capturing `codex://` links system-wide. Every clone inherited the official app's claim on `codex:`, `http:` and `https:`, and macOS binds one handler per scheme, so the most recently launched profile silently took every deep link — an MCP login could complete in a different profile than the one that started it. Each profile now declares only `codex-<name>:` and leaves the shared schemes to the official app.
- Report which application holds `codex:` in `doctor`.
- Find the bundled icons when the script is run through the `~/.local/bin` symlink the install instructions create. `BASH_SOURCE` reports the link rather than its target, so every sync from that path silently rebuilt profiles with the stock icon.
- Refuse to rebuild a profile whose application is running, instead of replacing the bundle underneath it; `sync` reports it and continues with the rest.

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
