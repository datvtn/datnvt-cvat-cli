from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from datnvt_cvat_cli.api import CVATClient
from datnvt_cvat_cli.models import DatasetFormat


def _make_client() -> CVATClient:
    return CVATClient("https://cvat.example.com", "user", "pass", 11)


class TestCVATClientAPI(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def test_check_connection_success(self):
        with patch.object(self.client, "_get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            self.assertTrue(self.client.check_connection())

    def test_check_project_failure_and_no_id(self):
        with patch.object(self.client, "_get") as mock_get:
            mock_get.side_effect = Exception("404")
            self.assertFalse(self.client.check_project(99))
        # zero project_id → False without any HTTP call
        self.assertFalse(CVATClient("https://x.com", "u", "p", 0).check_project())

    def test_upload_annotations_success(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("{}")
            anno_path = Path(f.name)
        try:
            with patch.object(self.client, "_put") as mock_put:
                mock_put.return_value = MagicMock(status_code=200)
                self.assertTrue(self.client.upload_annotations(147, anno_path, DatasetFormat.COCO))
        finally:
            anno_path.unlink()

    def test_upload_annotations_http_error(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("{}")
            anno_path = Path(f.name)
        try:
            with patch.object(self.client, "_put") as mock_put:
                mock_put.side_effect = requests.HTTPError("403")
                self.assertFalse(self.client.upload_annotations(147, anno_path))
        finally:
            anno_path.unlink()

    def test_download_tasks_skip_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            # default format is now CVAT for images 1.1 → annotations.xml
            anno = Path(tmp) / "task147" / "annotations.xml"
            anno.parent.mkdir(parents=True)
            anno.write_text("<annotations/>")
            with patch.object(self.client, "download_annotations") as mock_dl:
                self.client.download_tasks([147], out_dir=tmp, skip_existing=True)
                mock_dl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
