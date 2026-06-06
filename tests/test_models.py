from __future__ import annotations

import unittest

from pydantic import ValidationError

from datnvt_cvat_cli.models import ServerConfig


class TestServerConfig(unittest.TestCase):
    def test_valid_config(self):
        cfg = ServerConfig(
            url="https://cvat.example.com", username="u", password="p", project_id=11
        )
        self.assertEqual(cfg.url, "https://cvat.example.com")
        self.assertEqual(cfg.project_id, 11)

    def test_missing_required_field_raises(self):
        with self.assertRaises(ValidationError):
            ServerConfig(username="u", password="p")


if __name__ == "__main__":
    unittest.main()
