"""`unifi-door`: the helper the bar widget runs. Every command prints one JSON object."""

import argparse
import getpass
import json
import os
import sys
import tempfile
import time

from unifi import cli as unifi_cli
from unifi import config, connect
from unifi.errors import UnifiError
from unifi.transport import fetch_fingerprint, split_url

from . import access, protect


def _print(data):
    print(json.dumps(data))


def _error(exc):
    return {"ok": False, "error": exc.to_json()}


def snapshot_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    path = os.path.join(base, "omarchy-unifi-door")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def write_atomic(path, data):
    # The widget may read the file while the next picture lands: write next to
    # it and rename, so it only ever sees a whole JPEG.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def cmd_camera(args):
    """Which camera to show, plus the others to pick from."""
    _, endpoint, transport = unifi_cli._connect_or_fail(args.profile)
    cameras = protect.list_cameras(transport, endpoint)
    chosen = protect.choose_camera(cameras, args.camera)
    if not chosen:
        what = "no camera named '%s'" % args.camera if args.camera else "no camera in UniFi Protect"
        raise UnifiError("camera", what)
    _print({"ok": True, "camera": chosen, "cameras": cameras,
            "via": connect.describe(endpoint)})
    return 0


def cmd_snapshot(args):
    _, endpoint, transport = unifi_cli._connect_or_fail(args.profile)
    started = time.time()
    data = protect.fetch_snapshot(transport, endpoint, args.camera)
    if not data.startswith(b"\xff\xd8"):
        raise UnifiError("parse", "Protect did not return a JPEG")
    path = os.path.join(snapshot_dir(), "%s.jpg" % "".join(ch for ch in args.camera if ch.isalnum()))
    write_atomic(path, data)
    _print({"ok": True, "path": path, "bytes": len(data), "ms": int((time.time() - started) * 1000),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    return 0


def cmd_doors(args):
    client = access.AccessClient.for_profile(args.profile)
    doors = client.doors()
    chosen = access.choose_door(doors, args.door)
    if not chosen:
        raise UnifiError("http", "no door named '%s'" % args.door if args.door else "no door in UniFi Access")
    _print({"ok": True, "door": chosen, "doors": doors})
    return 0


def cmd_unlock(args):
    # Only ever run on an explicit request from the user (the panel asks for
    # a second click). The relay locks again by itself after the delay set in
    # Access.
    client = access.AccessClient.for_profile(args.profile)
    client.unlock(args.door)
    _print({"ok": True, "door": args.door, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    return 0


ACCESS_HELP = """UniFi Access is reached on the console itself (port %d), not through the
UniFi cloud: on the office network, or over a VPN to it.

The token comes from UniFi Access → Settings → General → API Token.
Give it only: Locations = Edit (to unlock), Device = View, System Log = View.""" % access.PORT


def cmd_access_setup(args):
    print(ACCESS_HELP + "\n")
    try:
        current = access.get_access(args.profile)
    except UnifiError:
        current = {}
    host = split_url(current["url"])[0] if current.get("url") else "10.10.1.1"
    host = unifi_cli._ask("Console address", host)
    url = access.default_url(host) if "://" not in host else host.rstrip("/")

    fingerprint = fetch_fingerprint(url)
    print("\nUniFi Access answers with this certificate:\n  %s" % fingerprint)
    if current.get("fingerprint") and current["fingerprint"] != fingerprint:
        print("  ⚠ This differs from the previously pinned certificate.")
    if not unifi_cli._confirm("Trust and pin it?"):
        return 1

    try:
        access.read_token(args.profile)
        keep = unifi_cli._confirm("Use the Access token already in the keyring?")
    except UnifiError:
        keep = False
    if not keep:
        token = getpass.getpass("UniFi Access API token (hidden): ").strip()
        if not token:
            return 1
        access.store_token(args.profile, token)

    client = access.AccessClient(url, access.read_token(args.profile), "pin", fingerprint)
    doors = client.doors()
    access.save_access(args.profile, url=url, tls="pin", fingerprint=fingerprint)
    print("\nConnected. Doors:")
    for door in doors:
        state = "locked" if door["locked"] else "unlocked"
        if door["position"]:
            state += ", " + door["position"]
        print("  • %s (%s)" % (door["fullName"] or door["name"], state))
    return 0


def cmd_setup(args):
    # Same profiles and keyring as the vcanuel.unifi plugin: one setup serves both.
    return unifi_cli.main(["--profile", args.profile, "setup"])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="unifi-door", description="UniFi door camera helper for the Omarchy bar")
    parser.add_argument("--profile", default="default", help="console profile (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)

    camera = sub.add_parser("camera", help="print the camera to show and the ones available")
    camera.add_argument("--camera", default="", help="camera name or id (default: the door camera)")
    camera.set_defaults(func=cmd_camera)

    snapshot = sub.add_parser("snapshot", help="save the camera's current picture and print its path")
    snapshot.add_argument("--camera", required=True, help="camera id")
    snapshot.set_defaults(func=cmd_snapshot)

    setup = sub.add_parser("setup", help="connect to a console (shared with the UniFi plugin)")
    setup.set_defaults(func=cmd_setup)

    doors = sub.add_parser("doors", help="print the door to show and the ones available (UniFi Access)")
    doors.add_argument("--door", default="", help="door name or id (default: the first one wired to a hub)")
    doors.set_defaults(func=cmd_doors)

    unlock = sub.add_parser("unlock", help="unlock a door now (UniFi Access)")
    unlock.add_argument("--door", required=True, help="door id")
    unlock.set_defaults(func=cmd_unlock)

    access_setup = sub.add_parser("access-setup", help="connect to UniFi Access on the console (LAN or VPN)")
    access_setup.set_defaults(func=cmd_access_setup)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UnifiError as exc:
        _print(_error(exc))
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130
