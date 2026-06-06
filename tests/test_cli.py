from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from datnvt_cvat_cli.cli import app

runner = CliRunner()

_SERVER_OPTS = [
    "--url",
    "https://cvat.example.com",
    "--username",
    "user",
    "--password",
    "pass",
    "--project-id",
    "11",
]


class TestCLI(unittest.TestCase):
    # --- config validation ---

    def test_missing_credentials_fails(self):
        result = runner.invoke(app, ["list-tasks"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Missing server config", result.output)

    # --- download ---

    def test_download_calls_client(self):
        with patch("datnvt_cvat_cli.cli.CVATClient") as MockClient:
            instance = MockClient.from_config.return_value
            with tempfile.TemporaryDirectory() as tmp:
                result = runner.invoke(
                    app, [*_SERVER_OPTS, "download", "-t", "147", "--out-dir", tmp]
                )
            self.assertEqual(result.exit_code, 0)
            call_kwargs = instance.download_tasks.call_args[1]
            self.assertEqual(call_kwargs["task_ids"], [147])

    # --- upload (per-task paths) ---

    def test_run_upload_per_task_paths(self):
        f1 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        f1.write("{}")
        f1.close()
        f2 = tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False)
        f2.write("<annotations/>")
        f2.close()
        yaml_content = f"""
- task: upload_anno_with_cvat_tasks
  parameters:
    dataset_format: "COCO 1.0"
    tasks:
      - task_id: 147
        annotation_path: {f1.name}
      - task_id: 150
        annotation_path: {f2.name}
        dataset_format: "CVAT for images 1.1"
"""
        yaml_file = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml_file.write(yaml_content)
        yaml_file.close()
        try:
            with patch("datnvt_cvat_cli.cli.CVATClient") as MockClient:
                instance = MockClient.from_config.return_value
                instance.check_connection.return_value = True
                instance.project_id = 11
                instance.check_project.return_value = True
                result = runner.invoke(app, [*_SERVER_OPTS, "run", yaml_file.name])
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(instance.upload_annotations.call_count, 2)
            self.assertEqual(instance.upload_annotations.call_args_list[0][0][0], 147)
            self.assertEqual(instance.upload_annotations.call_args_list[1][0][0], 150)
            instance.upload_tasks.assert_not_called()
        finally:
            Path(f1.name).unlink()
            Path(f2.name).unlink()
            Path(yaml_file.name).unlink()

    # --- pre-flight ---

    def test_run_preflight_connection_fails(self):
        yaml_file = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml_file.write(
            "- task: download_cvat_tasks\n  parameters:\n    task_ids: [147]\n    out_dir: /tmp\n"
        )
        yaml_file.close()
        try:
            with patch("datnvt_cvat_cli.cli.CVATClient") as MockClient:
                MockClient.from_config.return_value.check_connection.return_value = False
                result = runner.invoke(app, [*_SERVER_OPTS, "run", yaml_file.name])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Cannot connect", result.output)
        finally:
            Path(yaml_file.name).unlink()

    def test_run_preflight_project_not_found(self):
        yaml_file = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml_file.write(
            "- task: download_cvat_tasks\n  parameters:\n    task_ids: [147]\n    out_dir: /tmp\n"
        )
        yaml_file.close()
        try:
            with patch("datnvt_cvat_cli.cli.CVATClient") as MockClient:
                instance = MockClient.from_config.return_value
                instance.check_connection.return_value = True
                instance.project_id = 11
                instance.check_project.return_value = False
                result = runner.invoke(app, [*_SERVER_OPTS, "run", yaml_file.name])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("not found", result.output)
            instance.download_annotations.assert_not_called()
        finally:
            Path(yaml_file.name).unlink()


if __name__ == "__main__":
    unittest.main()
