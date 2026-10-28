# Troubleshooting

Start with:

```sh
multicodex --version
multicodex list
multicodex doctor
```

Review output before sharing it: diagnostics can contain local paths, profile names, and your signing identity.

## `multicodex: command not found`

From the cloned repository, run `./bin/multicodex --help`. Add the repository's `bin` directory to your shell's `PATH` using the [quick start](../README.md#quick-start). Keep the checkout in place; copying only the script loses its default icon path.

## Official app not found

The default source is `/Applications/ChatGPT.app`. Run `multicodex install`, or set `MULTICODEX_APP` to the actual official Codex app path, for example:

```sh
export MULTICODEX_APP="/Applications/Codex.app"
```

That setting also changes the install destination. Keep it consistent across terminals and commands. If a download fails signature, team, or bundle-identifier verification, do not bypass the check; report the error and use a separately obtained official app.

## Two profiles show the same account

Quit the affected profile apps and run `multicodex sync`, then launch each using `multicodex launch <name>` or its named Finder launcher. Current launchers supply `CODEX_HOME` and `CODEX_ELECTRON_USER_DATA_PATH` themselves. A pinned Dock icon may refer directly to the official app; use the named launcher to start the intended profile, and use the Dock to switch between running windows.

Fresh profiles require their own sign-in. MultiCodex does not copy your existing default account's credentials or settings into them.

## Updated Codex, but a profile is still old

Quit the profile, confirm `MULTICODEX_APP` points to the updated source, and run `multicodex sync <name>`. Then relaunch with the CLI. Both `CFBundleShortVersionString` and `CFBundleVersion` are tracked. Profiles created before build tracking are rebuilt on their next sync.

Sync skips a profile only when its recorded source version, build, and launcher revision match and its launcher executable exists. To rebuild a damaged or incorrectly branded launcher regardless of those checks, quit the profile and run `multicodex sync --force <name>`. Its account data stays in place.

## `list_threads`, `read_thread`, or `send_message_to_thread` are missing

Older MultiCodex launchers ran a locally re-signed Codex executable. The app-tools service checks code-signing identities in the calling process's ancestry and rejects that executable. Logs can show `dynamic_app_tools_peer_rejected reason=untrusted-code-signing-identity` and `Codex app tools pipe closed`, leaving the model without these tools even when its plugin is enabled.

Update MultiCodex, quit the affected profiles, and run:

```sh
multicodex sync
multicodex launch work
```

The new launcher executes the untouched official app with the existing profile directories. Reopen the chat and check its tools again. Finder launchers retain their profile names and colors; running instances use the official app's Dock branding and macOS privacy identity. The official app must remain installed at the path used during sync. If it moves, set `MULTICODEX_APP` and run `multicodex sync --force`.

This restores the trusted local connection; it does not grant another account access to a chat. A profile can read only chats available to its normal app tools. Asking a model to read a chat and opening a `codex://` URL in macOS are separate paths.

## Running profiles look the same in the Dock

In each running instance, open **Settings → Appearance → Advanced → Dock icon** and select a different built-in icon. Available choices include ChatGPT, Codex, and Space, depending on the app version and enabled options. See the [annotated walkthrough](../README.md#distinguish-running-profiles-in-the-dock). The preference is stored per profile and changes the icon at runtime without modifying the signed official app. The ten MultiCodex colors still identify the Finder and Spotlight launchers.

## A conversation fails with `failed to resolve rollout path`

After moving an existing profile, Codex's saved conversation records can still contain absolute paths to its old home. For example, a profile moved from `~/.codex-profiles/work` to `~/.multicodex/profiles/work` may list conversations but fail to open them.

Launching through MultiCodex automatically repairs the old `~/.codex-profiles/<name>` layout when the profile's conversation index references it and a matching session file exists in the current home. To repair a profile that is already running:

```sh
multicodex repair work
```

For a different old location, first check that the exact `sessions/.../rollout-....jsonl` file from the error exists in the current profile home, then run:

```sh
multicodex repair work --from /absolute/path/to/old/work
```

Use the old home shown in your error, belonging to that same profile. The command creates a compatibility symlink and refuses to replace an occupied path. Keep the link in place while saved records reference it. This restores access without rewriting the conversation database or copying credentials. Reopen the conversation; if the app still shows the cached error, quit the affected profile and relaunch it with `multicodex launch work`.

If the old location already exists, inspect it before changing anything. If the rollout file is also missing from the new home, a symlink cannot recover it; restore it from the original profile or a backup. Changing `MULTICODEX_ROOT` or running `sync` does not migrate saved paths.

## Shared conversations are missing or out of date

Session sharing is opt-in. `multicodex sync` updates application bundles; it does not share chats. For Default Codex and Work, run:

```sh
multicodex sessions enable work
multicodex sessions status work
```

Use the same `--with <peer>` argument for `sync`, `enable`, `status`, and `disable` when sharing two named profiles. The first run creates SQLite backups before merging. The agent repeats every 15 seconds while logged in and runs at login. macOS may delay background work or suspend it during sleep. `status` shows the last successful pass and the latest error, if any; its output includes the backup/log directory. Projects and the chats filed under them reach an app only while it is closed: quit it, wait about 15 seconds (or run `multicodex sessions sync work`), then reopen it. If `status` shows `sidebar_waiting_for_quit`, the listed app is still open.

The sync helper requires Python 3 and the repository's `tools/session_sync.py`. Keep the checkout and Python installation in place. If either moves, run `enable` again from the new checkout. If the two apps use different database schemas, sync stops before importing; update both apps, then rerun it. The integration uses Codex's local SQLite schema and may need an update after a Codex release.

Conversation files stay in their original profile homes and are referenced by both apps. Keep both homes and any legacy compatibility links available. Disabling sync leaves the imported conversations and these references in place. Backups include the indexes and paginated message history, not all attachments or rollout files; use a full profile backup before moving or removing either home.

Titles, pins, archive state, project metadata, and section assignments are merged. If both apps edit the same metadata between passes, the newest timestamp wins; ties prefer the home that sorts first by path. Deletions are not propagated: use Archive to hide a conversation in both apps. Avoid running the same conversation simultaneously in both apps, since their task execution and writer locks remain separate. Sharing history does not move running tasks, scheduled jobs, authentication, or account settings between apps.

## Permissions reset or signing fails

Profile launcher metadata changes require a new signature. `multicodex doctor` shows the selected signing identity; an ad-hoc signature is the fallback. The running app now uses the original official executable and its macOS privacy identity, so profiles share that runtime's Accessibility and Screen Recording permissions.

If you already have an appropriate identity in your Keychain, select it explicitly:

```sh
export MULTICODEX_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
```

Use your actual identity. Unlock your Keychain if necessary. A certificate is optional for local use, and selecting one does not guarantee that macOS will preserve every permission. Review requests in System Settings → Privacy & Security for the official app used by your profiles.

## Finder and Spotlight launcher icons look unchanged

Run `multicodex colors` to check that the generated icons are available. The repository's `assets/icons` directory must remain accessible. Creating or syncing a profile restarts the Dock to clear its icon cache. If it still looks stale:

```sh
killall Dock
```

The Dock disappears briefly and returns. If a launcher was built without its icon, restore the icon files, quit that profile, and run `multicodex sync --force <name>`. Running apps use the official app's built-in Dock icon preference instead of the launcher's color.

## Copies use more disk than expected

APFS cloning shares unchanged file data only when the source and destination support it on the same volume. A cross-volume copy, another filesystem, or changed files can consume additional space. File-size totals may also count shared blocks more than once. Electron data and account files consume their own space.

## Removing a profile or uninstalling

Use `multicodex remove <name>` for each profile you want to erase. It lists the affected paths and requires typing the profile name. This permanently deletes that profile's local data and app, so back up anything you need first.

After removing the desired profiles, delete the MultiCodex checkout and remove its `PATH` line from your shell configuration. Removing the checkout alone does not delete your profiles. The official app and default `~/.codex` directory remain separate.

## Reporting a bug

Include your MultiCodex version, macOS version, source app version/build, the failing command, expected result, and a redacted error message in a [GitHub issue](https://github.com/mahdi-salmanzade/MultiCodex/issues). Never attach profile directories or `auth.json`. For credential exposure, use the private route in [SECURITY.md](../SECURITY.md).
