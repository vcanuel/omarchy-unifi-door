"""`unifi-door`: the helper the bar widget runs. Every command prints one JSON object."""

import argparse
import json
import os
import sys
import tempfile
import time

from unifi import cli as unifi_cli
from unifi import config, connect
from unifi.errors import UnifiError

from . import protect


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

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except UnifiError as exc:
        _print(_error(exc))
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130
