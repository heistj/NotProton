# heistj/NotProton

A fork of [NotProtonNot/NotProton](https://github.com/NotProtonNot/NotProton). Upstream's
README still applies; this file covers only what differs.

## What this fork changes

- **CrossOver trial support.** Without a signed license, `CrossOverLicense.swift` accepts a
  trial for 14 days from CrossOver's `FirstRunDate`, and `compat_run.sh` repeats the check on
  every game launch.
- **Prelaunch script.** `make app` installs `app/prelaunch/launcher.sh` as the bundle's
  executable. It runs `app/prelaunch/prelaunch.py` before NotProton opens and blocks the launch
  if the script fails. Without Python, it opens Apple's Command Line Tools installer.
- **Updates come from this fork.** `SUFeedURL` and `SUPublicEDKey` in `app/Info.plist` point at
  this repository's releases and its own Sparkle key, so an update never swaps in an upstream
  build without the changes above.
- **Workflows run without upstream's runner.** `app.yml` and `release.yml` read the runner from
  the `MACOS_RUNNER` repository variable, falling back to upstream's `xcode-27`.

Each change touches few upstream lines, so merges stay small.

## Keeping up with upstream

Remotes in a working copy:

    git remote add upstream https://github.com/NotProtonNot/NotProton.git   # once

Then, whenever upstream moves:

    git switch main
    git fetch upstream
    git merge upstream/main
    git push origin main

Merge rather than rebase: `main` is published, and a rebase would rewrite it. Files most likely
to conflict are the ones listed above; `dylib/version.h` never does, because this fork does
not edit it (see below).

Avoid GitHub's **Sync fork → Discard commits** and `gh repo sync --force`: both reset `main` to
upstream and drop this fork's commits.

## Versions

A fork release is upstream's version plus a fork build number: `1.1.5.1`, `1.1.5.2`, and after
upstream ships 1.1.6, `1.1.6.1`. The release workflow passes it to `make app APP_VERSION=…`, so
`dylib/version.h` keeps upstream's value.

## Releasing

One-time setup:

1. **Settings → Actions → General:** allow Actions (forks start with them disabled).
2. **Settings → Secrets and variables → Actions:**
   - variable `MACOS_RUNNER` = a GitHub-hosted macOS runner with Xcode 27 at
     `/Applications/Xcode_27.0.app`, such as `macos-26`
   - secret `SPARKLE_PRIVATE_KEY` = the private half of this fork's Sparkle key

Then **Actions → release → Run workflow** with the version and release notes. It builds and
tests the app, signs the appcast, tags `v<version>`, and publishes the release.
