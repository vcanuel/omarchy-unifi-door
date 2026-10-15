import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from door import access  # noqa: E402
from unifi.errors import UnifiError  # noqa: E402


def raw_door(id, name, relay="lock", position="close", hub=True):
    return {"id": id, "name": name, "full_name": "Office / " + name, "door_lock_relay_status": relay,
            "door_position_status": position, "is_bind_hub": hub, "type": "door", "floor_id": "f"}


class NormalizeDoor(unittest.TestCase):
    def test_locked_closed(self):
        door = access.normalize_door(raw_door("d1", "Porte"))
        self.assertEqual(door, {"id": "d1", "name": "Porte", "fullName": "Office / Porte", "locked": True,
                                "position": "closed", "hasHub": True})

    def test_unlocked_open(self):
        door = access.normalize_door(raw_door("d1", "Porte", relay="unlock", position="open"))
        self.assertFalse(door["locked"])
        self.assertEqual(door["position"], "open")

    def test_no_position_sensor(self):
        for value in ("none", None):
            self.assertEqual(access.normalize_door(raw_door("d1", "Porte", position=value))["position"], "")


class ChooseDoor(unittest.TestCase):
    doors = [access.normalize_door(raw_door("a", "Spare", hub=False)), access.normalize_door(raw_door("b", "Porte"))]

    def test_first_with_hub(self):
        self.assertEqual(access.choose_door(self.doors)["id"], "b")

    def test_by_name_id_or_full_name(self):
        self.assertEqual(access.choose_door(self.doors, "spare")["id"], "a")
        self.assertEqual(access.choose_door(self.doors, "B")["id"], "b")
        self.assertEqual(access.choose_door(self.doors, "office / porte")["id"], "b")

    def test_unknown(self):
        self.assertIsNone(access.choose_door(self.doors, "nope"))
        self.assertIsNone(access.choose_door([]))


class FakeResponse:
    def __init__(self, status):
        self.status = status


class FakeTransport:
    def __init__(self, status, payload):
        self.status, self.payload, self.calls = status, payload, []

    def request(self, method, path, headers, body=None):
        self.calls.append((method, path, headers, body))
        raw = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return FakeResponse(self.status), raw


def client_with(status, payload):
    client = access.AccessClient.__new__(access.AccessClient)
    client.token = "secret-token"
    client.transport = FakeTransport(status, payload)
    return client


class Envelope(unittest.TestCase):
    def test_doors(self):
        client = client_with(200, {"code": "SUCCESS", "msg": "success", "data": [raw_door("d1", "Porte")]})
        self.assertEqual(client.doors()[0]["name"], "Porte")
        method, path, headers, body = client.transport.calls[0]
        self.assertEqual((method, path, body), ("GET", "/api/v1/developer/doors", None))
        self.assertEqual(headers["Authorization"], "Bearer secret-token")

    def test_unlock_is_a_put(self):
        client = client_with(200, {"code": "SUCCESS", "msg": "success", "data": None})
        client.unlock("d1")
        method, path, headers, body = client.transport.calls[0]
        self.assertEqual((method, path, body), ("PUT", "/api/v1/developer/doors/d1/unlock", b"{}"))
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_refused_code(self):
        client = client_with(200, {"code": "CODE_AUTH_FAILED", "msg": "token invalid", "data": None})
        with self.assertRaises(UnifiError) as caught:
            client.doors()
        self.assertEqual(caught.exception.kind, "auth")
        self.assertIn("token invalid", caught.exception.message)

    def test_http_403(self):
        client = client_with(403, {"code": "CODE_FORBIDDEN", "msg": "no permission"})
        with self.assertRaises(UnifiError) as caught:
            client.unlock("d1")
        self.assertEqual(caught.exception.kind, "auth")

    def test_not_json(self):
        client = client_with(200, b"<html>")
        with self.assertRaises(UnifiError) as caught:
            client.doors()
        self.assertEqual(caught.exception.kind, "parse")

    def test_token_never_in_errors(self):
        client = client_with(500, {"code": "X", "msg": "boom"})
        with self.assertRaises(UnifiError) as caught:
            client.doors()
        self.assertNotIn("secret-token", caught.exception.message)


if __name__ == "__main__":
    unittest.main()
