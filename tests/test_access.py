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


def raw_opening(id="", at=1729850000000, who="Vincent", provider="FACE", result="ACCESS",
                door_id="d1", actor_id="u1", issuer="i1"):
    # Shape of a hit from POST /api/v1/developer/system/logs (topic door_openings).
    return {"@timestamp": "2026-10-25T10:00:00Z", "_id": id, "tag": "access", "_source": {
        "actor": {"display_name": who, "id": actor_id, "type": "user"},
        "authentication": {"credential_provider": provider, "issuer": issuer},
        "event": {"type": "access.door.unlock", "result": result, "published": at, "display_message": ""},
        "target": [{"type": "UAH", "id": "hub", "display_name": "UA-HUB"},
                   {"type": "door", "id": door_id, "display_name": "Porte"}]}}


class Openings(unittest.TestCase):
    def test_normalize(self):
        opening = access.recent_openings([raw_opening(id="e1")])[0]
        self.assertEqual(opening, {"id": "e1", "at": 1729850000000, "who": "Vincent", "method": "Face",
                                   "granted": True, "doorId": "d1", "door": "Porte"})

    def test_unknown_person_and_method(self):
        opening = access.recent_openings([raw_opening(who="N/A", provider="SOME_NEW_THING", result="BLOCKED")])[0]
        self.assertEqual((opening["who"], opening["method"], opening["granted"]), ("", "Some New Thing", False))

    def test_newest_first_and_limit(self):
        hits = [raw_opening(at=1000 * i, actor_id="u%d" % i) for i in range(1, 8)]
        openings = access.recent_openings(hits, limit=3)
        self.assertEqual([o["at"] for o in openings], [7000, 6000, 5000])

    def test_other_doors_filtered(self):
        hits = [raw_opening(door_id="d1"), raw_opening(door_id="d2", at=2)]
        self.assertEqual([o["doorId"] for o in access.recent_openings(hits, "d1")], ["d1"])

    def test_same_event_twice_kept_once(self):
        # The controller can report one opening twice; only the shared fields match.
        hits = [raw_opening(id="a"), raw_opening(id="b"), raw_opening(id="a")]
        self.assertEqual(len(access.recent_openings(hits)), 1)

    def test_distinct_events_same_moment_kept(self):
        hits = [raw_opening(actor_id="u1"), raw_opening(actor_id="u2"), raw_opening(door_id="d2"),
                raw_opening(issuer="i2"), raw_opening(result="BLOCKED")]
        self.assertEqual(len(access.recent_openings(hits, limit=10)), 5)

    def test_without_timestamp_skipped(self):
        self.assertEqual(access.recent_openings([raw_opening(at=None), "junk"]), [])

    def test_request(self):
        client = client_with(200, {"code": "SUCCESS", "msg": "success", "data": {"hits": [raw_opening()]}})
        self.assertEqual(len(client.openings("d1")), 1)
        method, path, headers, body = client.transport.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(path.startswith("/api/v1/developer/system/logs?"))
        self.assertEqual(json.loads(body)["topic"], "door_openings")

    def test_empty_log(self):
        client = client_with(200, {"code": "SUCCESS", "msg": "success", "data": {"hits": None}})
        self.assertEqual(client.openings(), [])


if __name__ == "__main__":
    unittest.main()
