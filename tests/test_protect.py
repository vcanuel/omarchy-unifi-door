import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from door import protect  # noqa: E402


def cam(id, name, model, connected=True):
    return {"id": id, "name": name, "model": model, "connected": connected}


class ProtectPrefix(unittest.TestCase):
    def test_local(self):
        self.assertEqual(protect.protect_prefix({"apiPrefix": "/proxy/network"}), "/proxy/protect/integration/v1")

    def test_cloud_connector(self):
        endpoint = {"apiPrefix": "/v1/connector/consoles/ABC:1/proxy/network/"}
        self.assertEqual(protect.protect_prefix(endpoint), "/v1/connector/consoles/ABC:1/proxy/protect/integration/v1")


class ChooseCamera(unittest.TestCase):
    cameras = [cam("a", "Garden", "UVC G5 Bullet"), cam("b", "Porte - Entry", "UVC G6 Pro Entry")]

    def test_door_camera_by_default(self):
        self.assertEqual(protect.choose_camera(self.cameras)["id"], "b")

    def test_by_name_or_id(self):
        self.assertEqual(protect.choose_camera(self.cameras, "garden")["id"], "a")
        self.assertEqual(protect.choose_camera(self.cameras, "B")["id"], "b")

    def test_unknown_name(self):
        self.assertIsNone(protect.choose_camera(self.cameras, "nope"))

    def test_connected_door_camera_wins(self):
        cameras = [cam("x", "Old doorbell", "UVC G4 Doorbell", connected=False), cam("y", "Entry", "UVC G6 Pro Entry")]
        self.assertEqual(protect.choose_camera(cameras)["id"], "y")

    def test_falls_back_to_first_connected(self):
        cameras = [cam("x", "Off", "UVC G5", connected=False), cam("y", "On", "UVC G5")]
        self.assertEqual(protect.choose_camera(cameras)["id"], "y")

    def test_none(self):
        self.assertIsNone(protect.choose_camera([]))


class NormalizeCamera(unittest.TestCase):
    def test_fields(self):
        raw = {"id": "6ac", "name": "Porte - Entry", "type": "UVC G6 Pro Entry", "state": "CONNECTED",
               "featureFlags": {"hasSpeaker": True}, "hasPackageCamera": True}
        self.assertEqual(protect.normalize_camera(raw), {"id": "6ac", "name": "Porte - Entry", "model": "UVC G6 Pro Entry",
                                                         "connected": True, "hasSpeaker": True, "hasPackageCamera": True})


if __name__ == "__main__":
    unittest.main()
