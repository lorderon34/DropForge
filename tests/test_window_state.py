import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from settings import default_settings
from utils import json_load
from window_state import parse_window_geometry, window_geometry_is_visible


class ParseWindowGeometryTests(unittest.TestCase):
    def test_accepts_valid_saved_geometry(self):
        geometry = {"width": 1320, "height": 800, "x": -1200, "y": 40}
        self.assertEqual(parse_window_geometry(geometry), geometry)

    def test_rejects_missing_or_invalid_fields(self):
        self.assertIsNone(parse_window_geometry(None))
        self.assertIsNone(parse_window_geometry({"width": 1320, "height": 800, "x": 0}))
        self.assertIsNone(
            parse_window_geometry({"width": True, "height": 800, "x": 0, "y": 0})
        )

    def test_rejects_size_outside_supported_limits(self):
        self.assertIsNone(
            parse_window_geometry({"width": 1079, "height": 800, "x": 0, "y": 0})
        )
        self.assertIsNone(
            parse_window_geometry({"width": 1320, "height": 10001, "x": 0, "y": 0})
        )

    def test_old_settings_receive_the_new_default(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, "settings.json")
            path.write_text('{"dark_mode": true}', encoding="utf8")
            loaded = json_load(path, dict(default_settings))

        self.assertTrue(loaded["dark_mode"])
        self.assertIsNone(loaded["window_geometry"])

    def test_saved_geometry_survives_settings_merge(self):
        geometry = {"width": 1320, "height": 800, "x": -1600, "y": 100}
        with TemporaryDirectory() as directory:
            path = Path(directory, "settings.json")
            path.write_text(
                '{"window_geometry": '
                '{"width": 1320, "height": 800, "x": -1600, "y": 100}}',
                encoding="utf8",
            )
            loaded = json_load(path, dict(default_settings))

        self.assertEqual(loaded["window_geometry"], geometry)
        self.assertEqual(parse_window_geometry(loaded["window_geometry"]), geometry)


class WindowVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.geometry = {"width": 1320, "height": 800, "x": -1200, "y": 40}
        self.monitors = [(-1920, 0, 0, 1080), (0, 0, 1920, 1080)]

    def test_accepts_position_on_secondary_monitor(self):
        self.assertTrue(window_geometry_is_visible(self.geometry, self.monitors))

    def test_rejects_position_off_all_monitors(self):
        offscreen = {**self.geometry, "x": -4000}
        self.assertFalse(window_geometry_is_visible(offscreen, self.monitors))

    def test_rejects_window_with_only_a_sliver_visible(self):
        mostly_offscreen = {**self.geometry, "x": 1840, "y": 40}
        self.assertFalse(window_geometry_is_visible(mostly_offscreen, self.monitors))

    def test_requires_monitor_information(self):
        self.assertFalse(window_geometry_is_visible(self.geometry, []))


if __name__ == "__main__":
    unittest.main()
