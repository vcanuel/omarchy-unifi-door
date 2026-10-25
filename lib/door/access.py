"""UniFi Access developer API: the doors, their state, and remote unlock.

Unlike Protect, Access is not reachable through the UniFi cloud connector
(it answers "insufficient permissions for this endpoint"), and it does not
take the console's API key. It listens on the console itself, port 12445,
under /api/v1/developer, with its own self-signed certificate and a bearer
token created in Access → Settings → General → API Token. So it has its own
small config here (address and pinned certificate per profile) and its own
keyring entry for the token.

Every answer is an envelope: {"code": "SUCCESS", "data": ..., "msg": ...}.
"""

import json
import os
import subprocess
import time

from unifi.errors import UnifiError
from unifi.transport import Transport

PORT = 12445
PREFIX = "/api/v1/developer"
SECRET_SERVICE = "omarchy-unifi-door"
CONFIG_VERSION = 1


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "omarchy-unifi-door", "config.json")


def load_config():
    try:
        with open(config_path(), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"version": CONFIG_VERSION, "profiles": {}}
    except (OSError, ValueError) as exc:
        raise UnifiError("unconfigured", "cannot read %s: %s" % (config_path(), exc))
    data.setdefault("profiles", {})
    return data


def save_config(data):
    path = config_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def get_access(profile_name):
    access = load_config()["profiles"].get(profile_name, {}).get("access")
    if not access or not access.get("url"):
        raise UnifiError("unconfigured", "UniFi Access is not set up; run: unifi-door access-setup")
    return access


def save_access(profile_name, **fields):
    data = load_config()
    data["version"] = CONFIG_VERSION
    data["profiles"].setdefault(profile_name, {})["access"] = fields
    save_config(data)


def _secret_attrs(profile_name):
    return ["service", SECRET_SERVICE, "profile", profile_name]


def read_token(profile_name):
    try:
        result = subprocess.run(["secret-tool", "lookup"] + _secret_attrs(profile_name),
                                capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        raise UnifiError("unconfigured", "secret-tool is missing (install libsecret)")
    except subprocess.TimeoutExpired:
        raise UnifiError("unconfigured", "keyring did not answer; is it unlocked?")
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise UnifiError("unconfigured", "no UniFi Access token in the keyring; run: unifi-door access-setup")
    return token


def store_token(profile_name, token):
    result = subprocess.run(["secret-tool", "store", "--label=UniFi Access token (%s)" % profile_name]
                            + _secret_attrs(profile_name), input=token, capture_output=True, text=True)
    if result.returncode != 0:
        raise UnifiError("unconfigured", "could not store the token: %s" % (result.stderr.strip() or "secret-tool failed"))


def default_url(host):
    return "https://%s:%d" % (host, PORT)


class AccessClient:
    def __init__(self, url, token, tls="pin", fingerprint=None, timeout=5.0):
        self.token = token
        self.transport = Transport(url, None, tls=tls, fingerprint=fingerprint, timeout=timeout)

    @classmethod
    def for_profile(cls, profile_name):
        access = get_access(profile_name)
        return cls(access["url"], read_token(profile_name), access.get("tls", "pin"), access.get("fingerprint"))

    def call(self, method, path, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Authorization": "Bearer " + self.token, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        response, raw = self.transport.request(method, PREFIX + path, headers, body)
        try:
            envelope = json.loads(raw.decode("utf-8") or "null")
        except (UnicodeDecodeError, ValueError):
            envelope = None
        message = envelope.get("msg") if isinstance(envelope, dict) else ""
        if response.status in (401, 403):
            raise UnifiError("auth", "UniFi Access refused the token (HTTP %d%s)"
                             % (response.status, ": " + message if message else ""), response.status)
        if response.status >= 400:
            raise UnifiError("http", "UniFi Access returned HTTP %d%s"
                             % (response.status, ": " + message if message else ""), response.status)
        if not isinstance(envelope, dict):
            raise UnifiError("parse", "UniFi Access did not answer JSON")
        if envelope.get("code") != "SUCCESS":
            code = str(envelope.get("code") or "error")
            kind = "auth" if "TOKEN" in code or "AUTH" in code or "PERMISSION" in code else "http"
            raise UnifiError(kind, "UniFi Access: %s" % (message or code))
        return envelope.get("data")

    def doors(self):
        return [normalize_door(d) for d in (self.call("GET", "/doors") or []) if isinstance(d, dict)]

    def unlock(self, door_id):
        self.call("PUT", "/doors/%s/unlock" % door_id, {})

    def openings(self, door_id="", limit=5, days=7):
        """The door's latest openings and refusals from the system log, newest first."""
        since = int(time.time()) - days * 86400
        data = self.call("POST", "/system/logs?page_num=1&page_size=%d" % HISTORY_PAGE,
                         {"topic": "door_openings", "since": since})
        hits = data.get("hits") if isinstance(data, dict) else None
        return recent_openings(hits or [], door_id, limit)


def normalize_door(raw):
    position = raw.get("door_position_status")
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or raw.get("full_name") or "Door"),
        "fullName": str(raw.get("full_name") or raw.get("name") or ""),
        "locked": raw.get("door_lock_relay_status") != "unlock",
        # "open" / "closed", or "" when the door has no position sensor.
        "position": {"open": "open", "close": "closed"}.get(position, ""),
        "hasHub": bool(raw.get("is_bind_hub")),
    }


HISTORY_PAGE = 50

# authentication.credential_provider → what the panel says.
METHODS = {
    "NFC": "Card",
    "PIN_CODE": "PIN",
    "FACE": "Face",
    "MOBILE_TAP": "Phone",
    "MOBILE_BUTTON": "Phone",
    "TOUCH_PASS": "Touch Pass",
    "QR_CODE": "QR code",
    "WAVE": "Wave",
    "REMOTE_THROUGH_UAH": "Remote",
    "LICENSE_PLATE": "Plate",
}


def _door_target(source):
    for target in source.get("target") or []:
        if isinstance(target, dict) and target.get("type") == "door":
            return target
    return {}


def normalize_opening(hit):
    source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
    event = source.get("event") or {}
    actor = source.get("actor") or {}
    auth = source.get("authentication") or {}
    door = _door_target(source)
    published = event.get("published")
    at = int(published) if isinstance(published, (int, float)) and published > 0 else 0
    provider = str(auth.get("credential_provider") or "")
    name = str(actor.get("display_name") or "")
    return {
        "id": str(hit.get("_id") or ""),
        "at": at,  # milliseconds since the epoch
        "who": "" if name in ("", "N/A") else name,
        "method": METHODS.get(provider, provider.replace("_", " ").title()),
        "granted": event.get("result") == "ACCESS",
        "doorId": str(door.get("id") or ""),
        "door": str(door.get("display_name") or ""),
        # Fields both copies of one event share, like Home Assistant's fix
        # for the controller reporting each opening twice (core#185160).
        "_key": (at, event.get("result"), str(auth.get("issuer") or ""),
                 str(actor.get("id") or ""), str(door.get("id") or "")),
    }


def recent_openings(hits, door_id="", limit=5):
    seen, openings = set(), []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        opening = normalize_opening(hit)
        key = opening.pop("_key")
        if not opening["at"] or (door_id and opening["doorId"] and opening["doorId"] != door_id):
            continue
        if key in seen or (opening["id"] and opening["id"] in seen):
            continue
        seen.add(key)
        if opening["id"]:
            seen.add(opening["id"])
        openings.append(opening)
    openings.sort(key=lambda o: o["at"], reverse=True)
    return openings[:limit]


def choose_door(doors, wanted=""):
    """The door named or id'd by `wanted`, else the first one wired to a hub, else the first."""
    if not doors:
        return None
    wanted = str(wanted or "").strip().lower()
    if wanted:
        for door in doors:
            if wanted in (door["id"].lower(), door["name"].lower(), door["fullName"].lower()):
                return door
        return None
    for door in doors:
        if door["hasHub"]:
            return door
    return doors[0]
