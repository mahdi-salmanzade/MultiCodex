# MultiCodex

**Multiple Codex accounts. One Mac. Update Codex, run `sync`, keep working.**

MultiCodex lets you run multiple instances of the official ChatGPT desktop app, including Codex, side by side. Give work, personal, or client accounts their own named launcher, colored Finder icon, sign-in, and local profile—without repeatedly signing in and out.

![The built-in Dock icon picker showing ChatGPT, Codex, and Space](icons.png)

Choose a different built-in icon in each profile under **Settings → Appearance → Advanced → Dock icon**. The screenshot above shows the three choices in the current app; availability may vary by version. MultiCodex's ten custom colors identify the named Finder and Spotlight launchers. [See the annotated screenshots below](#distinguish-running-profiles-in-the-dock).

[Quick start](#quick-start) · [Features](#what-you-get) · [Updates](#updating) · [Commands](#commands) · [Troubleshooting](docs/TROUBLESHOOTING.md)

## Why MultiCodex exists

I built MultiCodex because I needed it. Codex Router stopped working for my setup, and after reaching out to its developer without hearing back, I decided to build a tool I could use myself.

My priority was simple: **running multiple Codex accounts should not mean waiting for a matching tool release whenever Codex updates.**

MultiCodex builds named launchers from the official app already installed on your Mac. The launchers carry your profile settings and execute the untouched official app. This keeps the original code-signing identity required by Codex's built-in chat tools. It does not patch Codex's JavaScript or maintain a modified version of its application code.

For ordinary updates, update the official app and run:

```sh
multicodex sync
```

Your profiles are rebuilt from the new app, keeping their account data and colors. There is no separate MultiCodex compatibility release to install for each routine Codex update.

This is an alternative for people who need **multiple desktop accounts running at once**. The Codex Router story above describes my experience, not a claim about every project with that name or its current status. MultiCodex still depends on the app's bundle layout and profile environment variables; an upstream change to those mechanisms may require a MultiCodex update.

## What you get

- **Accounts side by side.** Keep work, personal, and client sessions open at the same time.
- **Launch all your profiles.** `multicodex launch --all` starts them in sequence, skips apps already running, and reports startup failures.
- **Separate local profiles.** Each instance has its own Codex home and Electron data directory for credentials, settings, and local session state.
- **Named launchers.** Names such as `Codex work` and `Codex personal` and ten colored icons in Finder and Spotlight. Running instances use the official app's Dock/Cmd-Tab name and icon.
- **Simple updates.** Sync every profile or just one. Version and build checks flag profiles that need rebuilding, including updates with the same display version.
- **Efficient copies on APFS.** Copy-on-write cloning can share unchanged app data with the source. Actual space and speed depend on your filesystem, app size, and subsequent changes; other filesystems fall back to full copies.
- **Local profile management.** No MultiCodex account, hosted backend, telemetry, or request proxy. MultiCodex manages files and launches apps on your Mac.
- **Working built-in chat tools.** The original signed runtime can expose `list_threads`, `read_thread`, and `send_message_to_thread` to chats, subject to the app's normal tool availability.
- **A small tool you can inspect.** Bash and built-in macOS utilities. Generated icons are included. Optional conversation sharing requires Python 3; regenerating icons also requires Pillow.

Use it when you want to keep account contexts separate, recognize the right window at a glance, or work across several accounts without a sign-out/sign-in loop. MultiCodex does not add account quota, route requests to other model providers, or change what your accounts can access.

## Quick start

### Requirements

- **macOS 14+ with a compatible official app build.** OpenAI supports Apple silicon and Intel Macs; these changes have been validated on Apple silicon. See [OpenAI's current requirements](https://help.openai.com/en/articles/9275200-downloading-the-chatgpt-macos-app).
- Git to clone this repository. If needed, install Apple's command-line tools with `xcode-select --install`.
- The current ChatGPT desktop app that includes Codex, or use `multicodex install` below. ChatGPT Classic is a separate app and is not supported.
- APFS is recommended for space-efficient copies. A code-signing certificate is optional; ad-hoc signing is the fallback.

### 1. Get MultiCodex

```sh
git clone https://github.com/mahdi-salmanzade/MultiCodex.git
cd MultiCodex
export PATH="$PWD/bin:$PATH"
multicodex --version
```

That adds the command for the current terminal. To keep it available in new terminals using the default macOS zsh shell, run this **from the repository directory**:

```sh
printf '\nexport PATH="%s/bin:$PATH"\n' "$PWD" >> ~/.zshrc
source ~/.zshrc
```

Keep the cloned folder in place: the CLI reads its icons from `assets/icons` beside `bin`. You can also run `./bin/multicodex` from the repository without changing `PATH`.

### 2. Install or select the official app

If it is already installed at `/Applications/ChatGPT.app`, skip this step. That is the default bundle path used by this tool for the Codex app.

```sh
multicodex install
```

The installer downloads from OpenAI, verifies the app's signature, signing team, and bundle identifier before installing, and may request an administrator password to write to `/Applications`.

If your app lives somewhere else, set its path before using MultiCodex:

```sh
export MULTICODEX_APP="/Applications/Codex.app"
```

Use the actual path on your Mac and keep this setting consistent across commands. On Intel Macs, install the matching build from [OpenAI](https://chatgpt.com/download/) and select it here; Intel profiles have not been verified with these changes. See [configuration](#configuration) for persistence.

### 3. Create and launch your accounts

```sh
multicodex create work --color blue
multicodex create personal --color green

multicodex launch work
multicodex launch personal
```

Sign in to the intended account in each window. Both can stay open together. Omit `--color` to automatically pick an unused color.

Next time, start all your profiles with one command:

```sh
multicodex launch --all
```

Profiles start in sequence to avoid competing during startup. Already running profiles are skipped; each new app is given up to 30 seconds to appear as a running process. This checks process startup, not successful sign-in.

Start a profile with `multicodex launch <name>` or its named Finder or Spotlight launcher. Each launcher supplies that profile's isolation settings. Use the Dock or Cmd-Tab to switch between running windows; a pinned Dock icon may start the official app's default profile instead.

After updating an older MultiCodex checkout, quit your profiles and upgrade their launchers:

```sh
multicodex sync
```

Existing launchers that ran a re-signed copy are rebuilt by the next `multicodex sync`, even when the official app's version has not changed. This repairs missing built-in chat tools caused by the app-tools service rejecting the copy's code-signing identity. Keep the official source app installed at the configured path; every profile now runs that signed executable. Account data stays in the same profile directories.

```sh
multicodex list
multicodex doctor
```

`list` shows colors, whether a local `auth.json` exists, and update status. It does not validate the login with OpenAI. `doctor` reports the source app, signing identity, icon count, and filesystem information.

## Distinguish running profiles in the Dock

Use ChatGPT's built-in Dock icon preference to give up to three running instances different icons while keeping the official app's signature and direct chat tools working.

Open the intended profile from its named launcher, such as **Codex work**, and press **⌘,** to open Settings. Follow the numbered callouts in these screenshots:

1. Select **Appearance** in the Settings sidebar.
2. Expand **Advanced** at the bottom of the Appearance page.

![Annotated screenshot: select Appearance, then expand Advanced](docs/images/dock-icon-settings.png)

3. Scroll to **Dock icon** and choose **ChatGPT**, **Codex**, or **Space** when available.

![Annotated screenshot: find the Dock icon row and choose one of the three built-in icons](docs/images/dock-icon-picker.png)

Repeat in each profile, choosing a different icon. Each profile keeps its own preference. For example, use ChatGPT for your default account, Codex for work, and Space for personal. The available choices and layout can vary by app version; the screenshots show three options. The ten MultiCodex colors continue to identify the named Finder and Spotlight launchers.

## Updating

### Update Codex

1. Quit all running profiles and the default official app; they share the installed runtime.
2. Update the official app using its updater, then quit it again, or run `multicodex install` to reinstall the latest download.
3. Sync and relaunch:

```sh
multicodex sync
multicodex launch work
```

Or update a single profile:

```sh
multicodex sync personal
```

Sync replaces the profile's launcher bundle and preserves its name, color, bundle identifier, Codex home, and Electron data. Creating or syncing profiles briefly restarts the Dock to refresh cached launcher icons.

### Update MultiCodex itself

When you want fixes or features in this tool, run from your cloned repository:

```sh
git pull --ff-only
multicodex --version
```

There is no build step. After pulling launcher changes, quit your profiles and run `multicodex sync` to apply them. Updating MultiCodex and updating the official app are separate operations.

## Commands

| Command | What it does |
| --- | --- |
| `multicodex install` | Download, verify, and install the official app. Asks before reinstalling an existing copy. |
| `multicodex create <name> [--color <color>]` | Create an isolated profile and its branded, locally signed launcher. |
| `multicodex launch <name>` | Launch with the profile's isolation settings. |
| `multicodex launch --all` | Start every profile in sequence, skipping those already running. Aliases: `launch -a`, `open-all`, `openall`. |
| `multicodex list` | Show profiles, colors, local auth-file presence, and sync status. Alias: `ls`. |
| `multicodex sync [--force] [name]` | Rebuild outdated or missing launchers. `--force` rebuilds regardless of version. |
| `multicodex repair <name> [--from /old/profile/home]` | Restore access to sessions after moving a profile; defaults to the old `~/.codex-profiles/<name>` location. |
| `multicodex sessions sync <name> [--with <peer>]` | Sync conversations and message history both ways with `default` Codex or a named peer. Requires Python 3. |
| `multicodex sessions enable <name> [--with <peer>]` | Sync now and install a local agent that repeats every 15 seconds and at login. |
| `multicodex sessions disable <name> [--with <peer>]` | Stop the pair's automatic sync, retaining conversations and backups. |
| `multicodex sessions status <name> [--with <peer>]` | Show whether the agent is loaded, the last successful sync, and any last-attempt error. |
| `multicodex remove <name>` | Permanently delete the profile app and its local data after you type the profile name to confirm. Alias: `rm`. |
| `multicodex colors` | List the ten colors. Alias: `colours`. |
| `multicodex doctor` | Report installation, signing, icons, and filesystem details. |
| `multicodex --help` | Show usage. |
| `multicodex --version` | Show the MultiCodex version. |

Profile names accept letters, digits, dots, underscores, and hyphens; `.` and `..` are invalid. Use simple names such as `work`, `personal`, or `client-one`.

**Colors:** blue, green, purple, orange, red, teal, pink, yellow, indigo, graphite. Once all colors are used, automatic selection falls back to blue.

## On-device management and privacy

MultiCodex performs cloning, branding, signing, profile storage, and launching on your Mac. It does not send your credentials or conversations to a MultiCodex service. The `install` command accesses OpenAI's download server.

**Codex itself still connects to OpenAI and any services you configure.** Local profile management does not mean offline AI inference or that Codex never sends data over the network. Separate profiles are account and application-state separation, not operating-system sandboxes: they still run as your macOS user and can access files according to their permissions.

| Default location | Contents |
| --- | --- |
| `/Applications/ChatGPT.app` | Official source app. |
| `~/Applications/Codex <name>.app` | Named profile launcher, created locally from the source. |
| `~/.multicodex/profiles/<name>` | Profile's Codex home, including credentials and local session data. |
| `~/Library/Application Support/MultiCodex/<name>` | Profile's Electron data. |
| `~/.codex` | Default Codex home, shown as `default` in the list. Creating and launching profiles leave it separate; opt-in session sharing can modify its conversation and sidebar state. |

Back up profile data before removing a profile. `remove` deletes its local credentials, conversations, settings, and app; it does not delete the account at OpenAI.

When launching a moved profile, MultiCodex checks its conversation index for old `~/.codex-profiles/<name>` paths. If a referenced session exists in the current home, it restores the old location with a compatibility symlink. Existing directories and conflicting links are preserved. This check uses macOS's `sqlite3`; if unavailable, use `repair` explicitly. See [session path recovery](docs/TROUBLESHOOTING.md#a-conversation-fails-with-failed-to-resolve-rollout-path).

### Optional shared conversations

Profiles have separate conversation stores by default. To share Default Codex and a `work` profile on the same Mac:

```sh
multicodex sessions enable work
multicodex sessions status work
```

New conversations, message history, titles, archive state, project records, and section assignments sync in both directions. Use `--with personal` to select another named profile instead of Default Codex. Account credentials, settings, remote-control enrollment, scheduled jobs, and other account state remain separate. Stop automatic sync with `multicodex sessions disable work`.

The sidebar's projects and each chat's project live in the desktop app's own state file, which the app reads only at launch and overwrites while it runs. Sync matches projects by their folders and updates that file only while the app is closed, so a project added in one app appears in the other the next time it opens. `status` lists any app still waiting to be quit.

The first run backs up both conversation indexes and message-history databases under `~/.multicodex/session-sync`. It then merges an explicit set of conversation tables using SQLite transactions. Both profiles reference the original session files by absolute path; keep both profile homes in place. The helper does not copy the potentially large rollout files. Existing history databases are copied into the backup, and missing history is imported into the peer, so the first sync needs additional disk space and may take longer.

Automatic sync runs through a macOS LaunchAgent while you are logged in. Keep Python 3 and this checkout's `tools` directory available. After the first import, reopen the app if its sidebar is cached. See [sync behavior and limitations](docs/TROUBLESHOOTING.md#shared-conversations-are-missing-or-out-of-date).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MULTICODEX_APP` | `/Applications/ChatGPT.app` | Official source app; also the install destination. |
| `MULTICODEX_ROOT` | `~/.multicodex/profiles` | Root of profile Codex homes. Changing it does not migrate existing data. |
| `MULTICODEX_ICONS` | Repository's `assets/icons` | Directory containing the ten `.icns` variants. |
| `MULTICODEX_SIGNING_IDENTITY` | Automatically selected | Prefer a Developer ID Application identity, then Apple Development; fall back to ad-hoc signing (`-`). |

Add needed `export` lines to `~/.zshrc` to reuse them in new terminals. Use the same configuration for creating, launching, syncing, and removing profiles.

Re-signing is necessary for the branded launcher bundle because its metadata changes. The running app keeps the official source's signature and macOS privacy identity. Profile account and Electron data directories remain separate; privacy permissions are shared by the official runtime. See [troubleshooting](docs/TROUBLESHOOTING.md).

## How it works

1. Clone the installed official application, using APFS copy-on-write when available.
2. Set the profile's display name, bundle identifier (`local.multicodex.<name>`), and colored icon.
3. Remove `CFBundleIconName` so the app's asset catalog does not override the replacement `.icns`.
4. Give the copy a URL scheme of its own (`codex-<name>:`) and drop its claim on `codex:`, `http:` and `https:`.
5. Re-sign and verify the copy, then register it with Launch Services.
6. The launcher's executable starts the untouched official app with `CODEX_HOME`, `CODEX_ELECTRON_USER_DATA_PATH`, and `--user-data-dir` pointing at the profile's directories.

Step 4 keeps the branded launcher bundles from claiming the official app's URL schemes. The running runtime retains the official app's identity and protocol behavior. External `codex://` links do not encode a MultiCodex profile, so macOS may deliver them to another running instance of the official app. This fix restores the model's built-in chat-reference tools; it does not add profile-aware URL routing. `multicodex doctor` reports the registered handler.

Both environment variables matter. In the app behavior this tool was developed against, setting only `CODEX_HOME` can be overridden by the app's login-shell environment loading. The Electron data path keeps the profile configuration separate.

No OpenAI application bundle is included in this repository. Each user supplies or downloads the official app and creates their copies locally.

## Development and contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for checks, icon generation, and contribution guidance, and [CHANGELOG.md](CHANGELOG.md) for release notes. Report reproducible problems through [GitHub Issues](https://github.com/mahdi-salmanzade/MultiCodex/issues). For credential exposure or other security concerns, see [SECURITY.md](SECURITY.md).

```text
bin/multicodex          Bash CLI
assets/icons/          Ten generated profile icons
assets/electron.icns   Source artwork for icon generation
icons.png              Screenshot of the built-in Dock icon picker
docs/images/           Annotated settings screenshots
tools/make_icons.py    Optional icon generator
tools/session_sync.py  Optional conversation-sharing helper
tests/                 Isolated CLI and conversation-sharing tests
```

## License and credits

MultiCodex's original code and documentation are available under the [MIT License](LICENSE). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the OpenAI-derived icon artwork and third-party names, which are not relicensed under MIT.

Created by [Mahdi Salmanzade](https://github.com/mahdi-salmanzade). MultiCodex is an independent community project and is not affiliated with or endorsed by OpenAI. Codex and ChatGPT are OpenAI products.
