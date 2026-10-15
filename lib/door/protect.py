"""UniFi Protect integration API: which camera watches the door, and its picture.

Protect sits on the same console as Network and accepts the same API key, so
this reuses the unifi package's profiles and connection logic and only swaps
the path prefix: /proxy/network becomes /proxy/protect/integration/v1, both
on the LAN and through the cloud connector.
"""

NETWORK_PREFIX = "/proxy/network"
PROTECT_PREFIX = "/proxy/protect/integration/v1"

# Words in a camera's model name that mean it is mounted at a door.
DOOR_MODELS = ("entry", "doorbell", "intercom")


def protect_prefix(endpoint):
    prefix = str(endpoint.get("apiPrefix") or NETWORK_PREFIX).rstrip("/")
    if prefix.endswith(NETWORK_PREFIX):
        prefix = prefix[: -len(NETWORK_PREFIX)]
    return prefix + PROTECT_PREFIX


def normalize_camera(raw):
    flags = raw.get("featureFlags") or {}
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or raw.get("type") or "Camera"),
        "model": str(raw.get("type") or ""),
        "connected": raw.get("state") == "CONNECTED",
        "hasSpeaker": bool(flags.get("hasSpeaker")),
        "hasPackageCamera": bool(raw.get("hasPackageCamera")),
    }


def is_door_camera(camera):
    model = camera["model"].lower()
    return any(word in model for word in DOOR_MODELS)


def choose_camera(cameras, wanted=""):
    """The camera named or id'd by `wanted`, else the first door camera, else the first one.

    Connected cameras win over disconnected ones at each step, so a dead
    spare does not hide the live one.
    """
    if not cameras:
        return None
    wanted = str(wanted or "").strip().lower()
    ordered = sorted(cameras, key=lambda c: not c["connected"])
    if wanted:
        for camera in ordered:
            if wanted in (camera["id"].lower(), camera["name"].lower()):
                return camera
        return None
    for camera in ordered:
        if is_door_camera(camera):
            return camera
    return ordered[0]


def list_cameras(transport, endpoint):
    raw = transport.get_json(protect_prefix(endpoint) + "/cameras") or []
    return [normalize_camera(c) for c in raw if isinstance(c, dict)]


def fetch_snapshot(transport, endpoint, camera_id):
    path = "%s/cameras/%s/snapshot" % (protect_prefix(endpoint), camera_id)
    return transport.get_bytes(path, "image/jpeg")
