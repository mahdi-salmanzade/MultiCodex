# Contributing to MultiCodex

Thanks for helping make multiple Codex accounts easier to use on macOS.

## Development setup

Clone the repository and run `./bin/multicodex --help`. The CLI uses Bash and macOS utilities; optional session sharing also uses Python 3's standard library. There is no application build or runtime package install. Keep `bin`, `assets`, and `tools` in the same checkout.

Run the checks from the repository root:

```sh
bash -n bin/multicodex
shellcheck bin/multicodex
python3 -m unittest discover -s tests -v
```

Install ShellCheck separately if needed (`brew install shellcheck`). The tests use temporary profile directories and mocked application operations. They do not download Codex, launch account sessions, re-sign your real apps, or touch existing profile data. CI runs the same checks on macOS.

For changes to cloning, signing, or launch behavior, also manually verify on a Mac with a disposable profile: create it, launch it, check that its intended account is separate, quit it, sync it after an official app update, and check that its data remains. Remove the disposable profile only after confirming its name. Report the macOS version and source app version/build with your results. Automated tests do not establish compatibility with every official app release.

## Icons

The ten generated icons are committed, so normal users do not need Python or Pillow. To regenerate them on macOS:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install Pillow
python3 tools/make_icons.py
# Or regenerate one color:
python3 tools/make_icons.py --only red
```

Use `--source /path/to/source.icns` for other source artwork and `--out /path/to/output` for a temporary output directory. Check the result at small Dock sizes and in light and dark appearances. Respect the artwork exclusions in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Proposing changes

Open an issue describing the problem and a reproducible example. Keep changes focused and explain what users will experience, why the change is needed, and how it was checked. Maintainer work is committed directly to `main`; external contributors can share a patch or commit link in an issue.

Preserve these design choices:

- Create profiles from the user's installed official app.
- Avoid release-specific patches to Codex's application code.
- Keep account and Electron state separate, with both isolation variables supplied at launch.
- Keep profile management local and free of telemetry or a required backend.
- Preserve profile data during sync and require explicit confirmation before removal.
- Keep session sharing opt-in, back up conversation databases before the first merge, and never include account/enrollment tables in the sync allowlist.
- Document compatibility limits and distinguish local file checks from validated account status.

Do not include credentials, account data, local profiles, signing keys, downloaded application bundles, or identifying logs in contributions. Original code and documentation contributions are made under the project's MIT license.
