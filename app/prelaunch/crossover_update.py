# Updates CrossOver before NotProton opens, but only to a build this NotProton
# supports. A newer build NotProton cannot use yet gets a one-time warning
# instead, since installing it would leave NotProton unable to set up a runner.
#
# The download must carry CodeWeavers' Sparkle EdDSA signature, checked against
# the key in the installed CrossOver, and the app inside must be code signed by
# CodeWeavers' team. Nothing is installed without the user agreeing first.

import base64
import json
import os
import platform
import plistlib
import shutil
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import ed25519

FEED_URL = "https://www.codeweavers.com/xml/versions/cxmac.xml"
BUNDLE_ID = "com.codeweavers.CrossOver"
TEAM_ID = "9C6B7X7Z8E"
SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"

HOME = Path.home()
APP_LOCATIONS = [Path("/Applications/CrossOver.app"), HOME / "Applications" / "CrossOver.app"]
STATE_PATH = HOME / "Library" / "Application Support" / "notproton" / "prelaunch-state.json"
SUPPORTED_PATH = Path(__file__).with_name("supported-crossover.json")

# The feed is fetched at most this often, so most launches cost nothing.
CHECK_INTERVAL = 6 * 60 * 60
FEED_TIMEOUT = 15


@dataclass(frozen=True)
class Release:
    version: str
    display: str
    url: str
    ed_signature: str
    length: int
    minimum_macos: str


@dataclass(frozen=True)
class Installed:
    path: Path
    version: str
    public_key: str


@dataclass(frozen=True)
class Decision:
    action: str  # "update" or "warn"
    release: Release


def version_key(version):
    parts = []
    for part in version.split("."):
        parts.append(int(part) if part.isdigit() else -1)
    return tuple(parts)


def parse_feed(xml_bytes):
    releases = []
    for item in ET.fromstring(xml_bytes).iter("item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        version = enclosure.get(SPARKLE + "version")
        url = enclosure.get("url")
        signature = enclosure.get(SPARKLE + "edSignature")
        if not (version and url and signature):
            continue
        minimum = item.findtext(SPARKLE + "minimumSystemVersion") or "0"
        releases.append(Release(
            version=version,
            display=enclosure.get(SPARKLE + "shortVersionString") or version,
            url=url,
            ed_signature=signature,
            length=int(enclosure.get("length") or 0),
            minimum_macos=minimum.strip(),
        ))
    return releases


def plan(installed_version, releases, supported, state, macos_version):
    """What to offer, given the feed. Pure, so the policy can be tested on its own."""
    runnable = [r for r in releases if version_key(r.minimum_macos) <= version_key(macos_version)]
    newer = [r for r in runnable if version_key(r.version) > version_key(installed_version)]
    if not newer:
        return None
    newest = max(newer, key=lambda r: version_key(r.version))
    usable = [r for r in newer if r.version in supported]
    if usable:
        target = max(usable, key=lambda r: version_key(r.version))
        if target.version != state.get("declined"):
            return Decision("update", target)
    if newest.version not in supported and newest.version != state.get("warned"):
        return Decision("warn", newest)
    return None


def find_installed():
    for path in APP_LOCATIONS:
        try:
            with open(path / "Contents" / "Info.plist", "rb") as f:
                info = plistlib.load(f)
        except OSError:
            continue
        if info.get("CFBundleIdentifier") != BUNDLE_ID:
            continue
        return Installed(path, info.get("CFBundleVersion", ""), info.get("SUPublicEDKey", ""))
    return None


def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def load_supported():
    return set(json.loads(SUPPORTED_PATH.read_text()))


def _applescript_text(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def ask(title, message, ok, cancel):
    script = (
        f'display dialog "{_applescript_text(message)}" with title "{_applescript_text(title)}" '
        f'buttons {{"{cancel}", "{ok}"}} default button "{ok}" with icon caution'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.returncode == 0 and f"button returned:{ok}" in result.stdout


def tell(title, message):
    script = (
        f'display dialog "{_applescript_text(message)}" with title "{_applescript_text(title)}" '
        f'buttons {{"OK"}} default button "OK"'
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)


def notify(message):
    script = f'display notification "{_applescript_text(message)}" with title "NotProton"'
    subprocess.run(["osascript", "-e", script], capture_output=True)


def download(url, length, dest):
    request = urllib.request.Request(url, headers={"User-Agent": "NotProton prelaunch"})
    received = 0
    with urllib.request.urlopen(request, timeout=60) as response, open(dest, "wb") as out:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            received += len(chunk)
    if length and received != length:
        raise UpdateError(f"the download was {received} bytes, expected {length}")


class UpdateError(Exception):
    pass


def verify_signature(archive, release, installed):
    if not installed.public_key:
        raise UpdateError("the installed CrossOver carries no update key to check the download against")
    try:
        public = base64.b64decode(installed.public_key, validate=True)
        signature = base64.b64decode(release.ed_signature, validate=True)
    except ValueError as e:
        raise UpdateError(f"a key or signature is not valid base64: {e}")
    if not ed25519.verify_file(public, archive, signature):
        raise UpdateError("the download's signature does not match CodeWeavers' key")


def verify_app(app, release):
    with open(app / "Contents" / "Info.plist", "rb") as f:
        info = plistlib.load(f)
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        raise UpdateError(f"the download holds {info.get('CFBundleIdentifier')}, not CrossOver")
    if info.get("CFBundleVersion") != release.version:
        raise UpdateError(f"the download is build {info.get('CFBundleVersion')}, not {release.version}")
    check = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)],
                           capture_output=True, text=True)
    if check.returncode != 0:
        raise UpdateError(f"the downloaded app's code signature is invalid: {check.stderr.strip()}")
    details = subprocess.run(["codesign", "-dv", str(app)], capture_output=True, text=True).stderr
    if f"TeamIdentifier={TEAM_ID}" not in details.splitlines():
        raise UpdateError("the downloaded app is not signed by CodeWeavers")


def crossover_running():
    script = f'application id "{BUNDLE_ID}" is running'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.stdout.strip() == "true"


def quit_crossover():
    subprocess.run(["osascript", "-e", f'tell application id "{BUNDLE_ID}" to quit'], capture_output=True)
    for _ in range(20):
        if not crossover_running():
            return True
        time.sleep(0.5)
    return False


def replace_app(new_app, dest):
    """Swaps new_app in at dest, putting the old one back if the swap fails."""
    staged = dest.with_name(".CrossOver.app.new")
    backup = dest.with_name(".CrossOver.app.old")
    for leftover in (staged, backup):
        if leftover.exists():
            shutil.rmtree(leftover)
    subprocess.run(["ditto", str(new_app), str(staged)], check=True)
    os.rename(dest, backup)
    try:
        os.rename(staged, dest)
    except OSError:
        os.rename(backup, dest)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def install(release, installed):
    if not os.access(installed.path.parent, os.W_OK):
        raise UpdateError(f"{installed.path.parent} is not writable by this account")
    if crossover_running() and not quit_crossover():
        raise UpdateError("CrossOver is still open. Quit it and open NotProton again")

    notify(f"Downloading CrossOver {release.display}…")
    with tempfile.TemporaryDirectory(prefix="notproton-crossover-") as work:
        archive = Path(work) / "crossover.zip"
        print(f"downloading {release.url}")
        download(release.url, release.length, archive)
        verify_signature(archive, release, installed)
        print("signature verified")
        extracted = Path(work) / "extracted"
        subprocess.run(["ditto", "-x", "-k", str(archive), str(extracted)], check=True)
        app = extracted / "CrossOver.app"
        if not app.is_dir():
            raise UpdateError("the download does not contain CrossOver.app")
        verify_app(app, release)
        print("code signature verified")
        replace_app(app, installed.path)
    print(f"installed CrossOver {release.version} at {installed.path}")


def run(now=None):
    """Checks for a CrossOver update and acts on it. Never raises, so a failed check
    or update cannot keep NotProton from opening."""
    now = time.time() if now is None else now
    state = load_state()
    installed = find_installed()
    if installed is None:
        print("CrossOver is not installed, nothing to update")
        return
    if now - state.get("last_check", 0) < CHECK_INTERVAL:
        print("CrossOver update check ran recently, skipping")
        return

    try:
        request = urllib.request.Request(FEED_URL, headers={"User-Agent": "NotProton prelaunch"})
        with urllib.request.urlopen(request, timeout=FEED_TIMEOUT) as response:
            releases = parse_feed(response.read())
        supported = load_supported()
    except Exception as e:  # offline, feed down, or a malformed feed
        print(f"CrossOver update check skipped: {e}")
        return

    state["last_check"] = now
    decision = plan(installed.version, releases, supported, state, platform.mac_ver()[0])
    print(f"CrossOver {installed.version} installed; decision: "
          f"{decision.action + ' ' + decision.release.version if decision else 'none'}")

    if decision and decision.action == "warn":
        tell("CrossOver update",
             f"CrossOver {decision.release.display} is out, but this version of NotProton does not "
             f"support it yet. Keep CrossOver at its current version until a NotProton update adds it.")
        state["warned"] = decision.release.version
    elif decision and decision.action == "update":
        if ask("CrossOver update",
               f"CrossOver {decision.release.display} is available and supported by NotProton. "
               f"Download and install it now? NotProton opens when it finishes.",
               ok="Update", cancel="Not Now"):
            try:
                install(decision.release, installed)
                tell("CrossOver updated",
                     f"CrossOver {decision.release.display} is installed. Set up its compatibility "
                     f"tool in NotProton before playing.")
            except Exception as e:
                print(f"CrossOver update failed: {e}")
                tell("CrossOver was not updated", f"The update failed: {e}")
        else:
            state["declined"] = decision.release.version
    save_state(state)
