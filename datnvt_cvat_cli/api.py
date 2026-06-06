"""CVAT REST API client for annotation management."""

from __future__ import annotations

import io
import logging
import time
import zipfile
from pathlib import Path

import requests

from datnvt_cvat_cli.models import DATASET_FORMAT_QUERY_MAP, DatasetFormat, ServerConfig

logger = logging.getLogger(__name__)


class CVATClient:
    """REST API client for a CVAT server instance."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        project_id: int = 0,
    ) -> None:
        self.url = url.rstrip("/")
        self.project_id = project_id
        self._auth = (username, password)
        self._headers = {"Accept": "application/vnd.cvat+json"}

    @classmethod
    def from_config(cls, config: ServerConfig) -> CVATClient:
        return cls(config.url, config.username, config.password, config.project_id)

    # ------------------------------------------------------------------
    # Low-level HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **kwargs) -> requests.Response:
        resp = requests.get(
            f"{self.url}{path}",
            auth=self._auth,
            headers=self._headers,
            timeout=None,
            **kwargs,
        )
        resp.raise_for_status()
        return resp

    def _post(self, path: str, **kwargs) -> requests.Response:
        resp = requests.post(
            f"{self.url}{path}",
            auth=self._auth,
            headers=self._headers,
            timeout=None,
            **kwargs,
        )
        resp.raise_for_status()
        return resp

    def _put(self, path: str, **kwargs) -> requests.Response:
        resp = requests.put(
            f"{self.url}{path}",
            auth=self._auth,
            headers=self._headers,
            timeout=None,
            **kwargs,
        )
        resp.raise_for_status()
        return resp

    def _wait_for_request(
        self,
        rq_id: str,
        poll_interval: float = 1.0,
        timeout: int = 600,
    ) -> None:
        """Poll /api/requests/{rq_id} until status is 'finished'."""
        deadline = time.time() + timeout
        while True:
            resp = self._get(f"/api/requests/{rq_id}")
            status = resp.json().get("status")
            if status == "finished":
                return
            if status == "failed":
                raise RuntimeError(f"CVAT async request {rq_id} reported failure")
            if time.time() > deadline:
                raise TimeoutError(
                    f"CVAT async request {rq_id} did not finish within {timeout}s",
                )
            time.sleep(poll_interval)

    def _paginate(self, path: str, params: dict | None = None) -> list[dict]:
        """Collect all pages from a paginated CVAT list endpoint."""
        params = dict(params or {})
        params.setdefault("page_size", 100)
        params["page"] = 1
        results: list[dict] = []
        while True:
            data = self._get(path, params=params).json()
            results.extend(data.get("results", []))
            if not data.get("next"):
                break
            params["page"] += 1
        return results

    # ------------------------------------------------------------------
    # Connection / discovery
    # ------------------------------------------------------------------

    def check_connection(self) -> bool:
        """Return True if credentials are valid and the server is reachable."""
        try:
            self._get("/api/users/self")
            return True
        except Exception:
            return False

    def check_project(self, project_id: int | None = None) -> bool:
        """Return True if the given project exists and is accessible.

        Falls back to self.project_id when project_id is None.
        Returns False immediately when no project_id is configured.
        """
        pid = project_id if project_id is not None else self.project_id
        if not pid:
            return False
        try:
            self._get(f"/api/projects/{pid}")
            return True
        except Exception:
            return False

    def get_projects(self) -> list[dict]:
        """List all projects accessible to the authenticated user."""
        return self._paginate("/api/projects")

    def get_tasks(self, project_id: int | None = None) -> list[dict]:
        """List all tasks, optionally filtered by project."""
        pid = project_id if project_id is not None else self.project_id
        params = {"project_id": pid} if pid else {}
        return self._paginate("/api/tasks", params)

    def get_task_ids(self, project_id: int | None = None) -> list[int]:
        """Return only the task IDs for the given project."""
        return [t["id"] for t in self.get_tasks(project_id)]

    def get_task_info(self, task_id: int) -> dict:
        """Return full metadata dict for a single task."""
        return self._get(f"/api/tasks/{task_id}").json()

    # ------------------------------------------------------------------
    # Download helpers
    # ------------------------------------------------------------------

    def _extract_zip(self, zip_bytes: bytes, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(dest)

    def _download_annotations_new_api(
        self,
        task_id: int,
        fmt: DatasetFormat,
    ) -> bytes:
        """CVAT 2.x: POST annotations/export → poll → GET download."""
        format_name = DATASET_FORMAT_QUERY_MAP[fmt]
        resp = self._post(
            f"/api/tasks/{task_id}/annotations/export",
            params={"format": format_name},
        )
        rq_id = resp.json().get("rq_id")
        if not rq_id:
            raise ValueError("No rq_id in annotations/export response")
        self._wait_for_request(rq_id)
        dl = self._get(
            f"/api/tasks/{task_id}/annotations/export",
            params={"format": format_name, "rq_id": rq_id, "action": "download"},
            stream=True,
        )
        return dl.content

    def _download_annotations_legacy(
        self,
        task_id: int,
        fmt: DatasetFormat,
    ) -> bytes:
        """Legacy: POST dataset/export to prime cache, then GET annotations download."""
        try:
            self._post(
                f"/api/tasks/{task_id}/dataset/export",
                params={"save_images": False, "format": fmt.value},
            )
        except Exception:
            pass

        req_path = f"/api/tasks/{task_id}/annotations"
        params = {"format": fmt.value, "action": "download"}
        for attempt in range(6):
            try:
                resp = requests.get(
                    f"{self.url}{req_path}",
                    params=params,
                    auth=self._auth,
                    headers=self._headers,
                    timeout=None,
                )
                if resp.status_code == 200:
                    return resp.content
                # 202 = export still processing; other non-OK → raise
                if resp.status_code != 202:
                    resp.raise_for_status()
            except requests.HTTPError:
                if attempt == 5:
                    raise
            time.sleep(2**attempt)
        raise RuntimeError(
            f"Could not download annotations for task {task_id} after retries",
        )

    def _download_with_images(
        self,
        task_id: int,
        out_path: Path,
        fmt: DatasetFormat,
    ) -> Path:
        """Download the full dataset (annotations + images) via dataset/export."""
        out_path.mkdir(parents=True, exist_ok=True)
        resp = self._post(
            f"/api/tasks/{task_id}/dataset/export",
            params={
                "format": fmt.value,
                "save_images": True,
                "filename": f"task_{task_id}_dataset",
            },
        )
        rq_id = resp.json().get("rq_id")
        if not rq_id:
            raise ValueError("No rq_id received from dataset/export")
        self._wait_for_request(rq_id)

        dl = self._get(
            f"/api/tasks/{task_id}/dataset",
            params={"format": fmt.value, "action": "download"},
            stream=True,
        )
        zip_path = out_path / "_dataset.zip"
        with open(zip_path, "wb") as f:
            for chunk in dl.iter_content(chunk_size=8192):
                f.write(chunk)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(out_path)
        zip_path.unlink()
        return out_path

    # ------------------------------------------------------------------
    # Public download API
    # ------------------------------------------------------------------

    def download_annotations(
        self,
        task_id: int,
        out_path: Path,
        fmt: DatasetFormat = DatasetFormat.CVAT,
        save_images: bool = False,
    ) -> Path:
        """Download a single task to *out_path*.

        Args:
            task_id: CVAT task ID.
            out_path: Destination directory.
            fmt: Annotation format.
            save_images: When True, also download the raw images alongside
                annotations (uses the higher-privilege dataset/export endpoint).
        """
        out_path = Path(out_path)
        if save_images:
            return self._download_with_images(task_id, out_path, fmt)

        # Try new CVAT 2.x endpoint first; fall back to legacy
        zip_bytes: bytes | None = None
        try:
            zip_bytes = self._download_annotations_new_api(task_id, fmt)
            logger.debug(f"Task {task_id}: used annotations/export endpoint")
        except Exception as exc:
            logger.warning(
                f"Task {task_id}: annotations/export failed ({exc}), trying legacy",
            )

        if zip_bytes is None:
            zip_bytes = self._download_annotations_legacy(task_id, fmt)
            logger.debug(f"Task {task_id}: used legacy annotations endpoint")

        self._extract_zip(zip_bytes, out_path)
        logger.info(f"Task {task_id}: annotations saved to {out_path}")
        return out_path

    def download_tasks(
        self,
        task_ids: list[int],
        out_dir: str | None = None,
        out_paths: list[Path] | None = None,
        fmt: DatasetFormat = DatasetFormat.CVAT,
        save_images: bool = False,
        skip_existing: bool = True,
        folder_prefix: str = "task",
    ) -> None:
        """Download multiple tasks in sequence.

        Subdirectories are named ``{folder_prefix}{id}/`` when *out_dir* is used
        (default prefix is ``task``, e.g. ``task147/``).
        """
        paths = self._resolve_out_paths(task_ids, out_dir, out_paths, folder_prefix)
        for task_id, path in zip(task_ids, paths):
            if skip_existing and self._has_annotations(path, fmt):
                logger.info(f"Task {task_id}: already downloaded, skipping")
                continue
            logger.info(f"Task {task_id}: downloading → {path}")
            try:
                self.download_annotations(task_id, path, fmt, save_images)
            except Exception as exc:
                logger.error(f"Task {task_id}: download failed — {exc}")

    # ------------------------------------------------------------------
    # Upload API
    # ------------------------------------------------------------------

    def upload_annotations(
        self,
        task_id: int,
        anno_path: Path,
        fmt: DatasetFormat = DatasetFormat.CVAT,
    ) -> bool:
        """Upload an annotation file to a CVAT task.

        Args:
            task_id: Target CVAT task.
            anno_path: Path to the annotation file (JSON for COCO, XML for CVAT).
            fmt: Format of the annotation file.

        Returns:
            True on success, False on failure.
        """
        format_name = DATASET_FORMAT_QUERY_MAP[fmt]
        with open(anno_path, encoding="utf-8") as fh:
            content = fh.read()

        filename = "annotations.json" if fmt == DatasetFormat.COCO else "annotations.xml"
        mime = "application/json" if fmt == DatasetFormat.COCO else "application/xml"
        files = {"annotation_file": (filename, content, mime)}

        try:
            resp = self._put(
                f"/api/tasks/{task_id}/annotations",
                params={"format": format_name},
                files=files,
            )
            if resp.status_code in (200, 201, 202):
                logger.info(f"Task {task_id}: annotations uploaded successfully")
                return True
            logger.error(f"Task {task_id}: upload returned {resp.status_code}")
            return False
        except requests.HTTPError as exc:
            logger.error(f"Task {task_id}: upload failed — {exc}")
            return False

    def upload_tasks(
        self,
        task_ids: list[int],
        in_dir: str,
        fmt: DatasetFormat = DatasetFormat.CVAT,
    ) -> None:
        """Upload annotations for multiple tasks from ``in_dir/task{id}/`` subdirs.

        Looks for ``annotations/instances_default_pseudo.json`` (COCO) or
        ``annotations_pseudo.xml`` (CVAT) inside each task folder; falls back
        to the non-pseudo variant if the pseudo file doesn't exist.
        """
        for task_id in task_ids:
            task_dir = Path(in_dir) / f"task{task_id}"
            if fmt == DatasetFormat.COCO:
                candidates = [
                    task_dir / "annotations" / "instances_default_pseudo.json",
                    task_dir / "annotations" / "instances_default.json",
                ]
            else:
                candidates = [
                    task_dir / "annotations_pseudo.xml",
                    task_dir / "annotations.xml",
                ]

            anno_file = next((c for c in candidates if c.exists()), None)
            if anno_file is None:
                logger.warning(
                    f"Task {task_id}: no annotation file found under {task_dir}",
                )
                continue

            logger.info(f"Task {task_id}: uploading {anno_file}")
            self.upload_annotations(task_id, anno_file, fmt)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_out_paths(
        self,
        task_ids: list[int],
        out_dir: str | None,
        out_paths: list[Path] | None,
        folder_prefix: str = "task",
    ) -> list[Path]:
        if out_paths:
            return [Path(p) for p in out_paths]
        if out_dir:
            return [Path(out_dir) / f"{folder_prefix}{tid}" for tid in task_ids]
        raise ValueError("Provide either out_dir or out_paths")

    def _annotation_path(self, base: Path, fmt: DatasetFormat) -> Path:
        if fmt == DatasetFormat.COCO:
            return base / "annotations" / "instances_default.json"
        return base / "annotations.xml"

    def _has_annotations(self, path: Path, fmt: DatasetFormat) -> bool:
        return self._annotation_path(path, fmt).exists()
