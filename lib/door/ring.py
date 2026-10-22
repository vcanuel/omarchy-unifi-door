"""The doorbell, from anywhere: UniFi Protect pushes, the widget subscribes.

Protect's own event stream (a websocket under /subscribe/events) is not
relayed by the UniFi cloud connector, so away from the office nothing can
listen to the console. Instead an Alarm Manager rule on the console ("Doorbell
ring" → Webhook) posts to an ntfy topic, and the widget keeps a streaming
subscription to that topic open. Both sides only make outgoing connections,
so this works on any network.

The topic name is the only secret: anyone who knows it can read and post to
it. It is random, kept in ~/.config/omarchy-unifi-door/config.json (0600),
and never shown in the bar.
"""

import http.client
import json
import os
import secrets
import socket
import ssl
import time
from urllib.parse import quote, urlsplit

from unifi.errors import UnifiError

from . import access

DEFAULT_SERVER = "https://ntfy.sh"
# ntfy sends a keepalive every 45 seconds; silence well past that means the
# connection is dead even if TCP has not noticed.
READ_TIMEOUT = 120
# On reconnect, rings older than this are history, not someone at the door.
FRESH_SEC = 90


def new_topic():
    return "unifi-door-" + secrets.token_urlsafe(18).replace("_", "").replace("-", "")[:24]


def get_ring(profile_name):
    ring = access.load_config()["profiles"].get(profile_name, {}).get("ring")
    if not ring or not ring.get("topic"):
        raise UnifiError("unconfigured", "the doorbell is not set up; run: unifi-door ring-setup")
    return ring


def save_ring(profile_name, **fields):
    data = access.load_config()
    data["version"] = access.CONFIG_VERSION
    data["profiles"].setdefault(profile_name, {})["ring"] = fields
    access.save_config(data)
    os.chmod(access.config_path(), 0o600)


def topic_url(ring):
    return "%s/%s" % (str(ring.get("server") or DEFAULT_SERVER).rstrip("/"), quote(ring["topic"]))


def _connection(url, timeout):
    parts = urlsplit(url)
    if parts.scheme == "https":
        return http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=timeout,
                                           context=ssl.create_default_context())
    return http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)


def publish(ring, message):
    """Post a message to the topic, as the console's webhook does."""
    url = topic_url(ring)
    conn = _connection(url, 10)
    try:
        conn.request("POST", urlsplit(url).path, body=message.encode(), headers={"Title": "UniFi Door"})
        response = conn.getresponse()
        response.read()
        if response.status >= 300:
            raise UnifiError("http", "ntfy answered HTTP %d" % response.status)
    except (OSError, http.client.HTTPException) as exc:
        raise UnifiError("unreachable", "ntfy did not answer: %s" % exc)
    finally:
        conn.close()


def parse_event(line):
    """One line of ntfy's JSON stream, or None for keepalives and noise."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("event") != "message":
        return None
    return {"id": str(event.get("id") or ""), "time": int(event.get("time") or 0),
            "message": str(event.get("message") or "")}


def is_fresh(event, now=None):
    return (now if now is not None else time.time()) - event["time"] <= FRESH_SEC


def stream(ring, since=None):
    """Yield ring events from the topic until the connection drops.

    `since` is the id of the last event seen, so a ring that lands during a
    reconnect is not lost; without it only new events come.
    """
    url = topic_url(ring)
    path = urlsplit(url).path + "/json" + ("?since=%s" % quote(since) if since else "")
    conn = _connection(url, READ_TIMEOUT)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        if response.status != 200:
            raise UnifiError("http", "ntfy answered HTTP %d" % response.status)
        while True:
            line = response.fp.readline()
            if not line:
                return
            event = parse_event(line)
            if event:
                yield event
    except (OSError, socket.timeout, http.client.HTTPException) as exc:
        raise UnifiError("unreachable", "ntfy did not answer: %s" % exc)
    finally:
        conn.close()
