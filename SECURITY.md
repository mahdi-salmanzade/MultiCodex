# Security

MultiCodex manages local application copies and profile directories that may contain credentials. It does not operate a hosted service or proxy Codex requests.

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** feature for private reports:

[Report a vulnerability privately](https://github.com/mahdi-salmanzade/MultiCodex/security/advisories/new)

Include the MultiCodex version, macOS version, source app version/build, reproduction steps, and expected impact. Use synthetic examples. Do not upload `auth.json`, account tokens, conversations, signing certificates, or private keys.

If private reporting is unavailable, open a public issue asking for a private contact method without including exploit details or secrets.

## Scope

Please report issues involving profile-path handling, accidental sharing or deletion of profile state, download verification, or credential exposure in this tool. Bugs in the official Codex application itself should be reported to OpenAI.

Separate profiles do not provide an operating-system sandbox. They run under the same macOS user. For network behavior of Codex and configured integrations, consult those services' documentation.

Only the latest MultiCodex release is maintained; fixes are published here as they become available. There is no guaranteed response time.
