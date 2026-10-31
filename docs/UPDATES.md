# App updates

Version 0.5.1 adds updates to both Client and Server.
Earlier installed versions need one manual update to gain this feature.

TripleSense checks the latest stable GitHub release on startup by default.
When a newer installer exists for your computer, **Update available** appears
beside Logs and Settings. Open it, download the update, then choose
**Install and restart**. TripleSense disconnects the controller before replacing
the app, keeps settings and pairings, and reopens afterward. You may see the
normal Windows/macOS/Linux administrator prompt.

**Settings → Updates** checks manually. **Check for updates automatically**
turns startup checks on or off. Downloads show progress and must match the
release asset's published SHA-256 digest before installation. Updates never
automatically downgrade a newer development build or install prereleases.

Public releases need no GitHub account. While the repository remains private,
open **GitHub access** in Updates and supply a fine-grained token with read-only
Contents access to arwebSE/TripleSense. The token stays in Windows Credential
Manager, macOS Keychain or the Linux system credential store. No developer's
token is bundled with the app. Leave the field empty and save to remove access.

Windows uses the existing installer. macOS verifies the downloaded app's bundle
identity, version and code signature, stages it, then replaces the installed
bundle after quitting; the previous bundle is restored if replacement fails.
The Linux Debian/Ubuntu package uses the system package installer.

Download and startup checks do not interrupt a controller session. Installation
does disconnect it. If installation fails or authorization is cancelled, the
helper reopens the installed app where possible; diagnostic details go to
`update-install.log` in the app's private data directory.
