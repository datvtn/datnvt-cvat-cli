"""Typer-based CLI for datnvt-cvat-cli."""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

import typer
import yaml
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from datnvt_cvat_cli.api import CVATClient
from datnvt_cvat_cli.models import DatasetFormat, ServerConfig

logger = logging.getLogger(__name__)
console = Console()
app = typer.Typer(
    name="cvat-cli",
    help="Manage CVAT annotations: download, upload, sync, and inspect tasks.",
    no_args_is_help=True,
)

# ---------------------------------------------------------------------------
# Server config resolution
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATHS = ["config/server.yaml", "server.yaml"]


def _resolve_server_config(
    config_file: str | None,
    url: str | None,
    username: str | None,
    password: str | None,
    project_id: int | None,
) -> ServerConfig:
    """Build ServerConfig from (priority high→low): CLI args > YAML file > env vars."""
    # Base: environment variables
    cfg: dict = {
        "url": os.environ.get("CVAT_URL"),
        "username": os.environ.get("CVAT_USERNAME"),
        "password": os.environ.get("CVAT_PASSWORD"),
        "project_id": (
            int(os.environ["CVAT_PROJECT_ID"]) if os.environ.get("CVAT_PROJECT_ID") else None
        ),
    }

    # YAML file overrides env vars
    config_path = config_file or os.environ.get("CVAT_SERVER_CONFIG")
    if config_path is None:
        for default in _DEFAULT_CONFIG_PATHS:
            if Path(default).exists():
                config_path = default
                break

    if config_path and Path(config_path).exists():
        with open(config_path) as fh:
            file_cfg = yaml.safe_load(fh) or {}
        for key in ("url", "username", "password", "project_id"):
            if file_cfg.get(key) is not None:
                cfg[key] = file_cfg[key]
    elif config_path:
        console.print(f"[yellow]Warning:[/yellow] config file not found: {config_path}")

    # CLI args have highest priority
    if url is not None:
        cfg["url"] = url
    if username is not None:
        cfg["username"] = username
    if password is not None:
        cfg["password"] = password
    if project_id is not None:
        cfg["project_id"] = project_id

    missing = [k for k in ("url", "username", "password") if not cfg.get(k)]
    if cfg.get("project_id") is None:
        missing.append("project_id")

    if missing:
        console.print(
            f"[red]Error:[/red] Missing server config: {', '.join(missing)}.\n"
            "Provide --config, set CVAT_SERVER_CONFIG env var, or use --url/--username/--password/--project-id.",
        )
        raise typer.Exit(code=1)

    return ServerConfig(**cfg)


def _make_client(ctx: typer.Context) -> CVATClient:
    obj = ctx.obj or {}
    cfg = _resolve_server_config(
        obj.get("config_file"),
        obj.get("url"),
        obj.get("username"),
        obj.get("password"),
        obj.get("project_id"),
    )
    return CVATClient.from_config(cfg)


# ---------------------------------------------------------------------------
# Global callback — captures shared server options
# ---------------------------------------------------------------------------


@app.callback()
def main(
    ctx: typer.Context,
    config_file: Optional[str] = typer.Option(
        None,
        "--config",
        "-c",
        envvar="CVAT_SERVER_CONFIG",
        help="Path to server config YAML.",
    ),
    url: Optional[str] = typer.Option(
        None,
        "--url",
        envvar="CVAT_URL",
        help="CVAT server URL.",
    ),
    username: Optional[str] = typer.Option(
        None,
        "--username",
        "-u",
        envvar="CVAT_USERNAME",
        help="CVAT username.",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        "-p",
        envvar="CVAT_PASSWORD",
        help="CVAT password.",
    ),
    project_id: Optional[int] = typer.Option(
        None,
        "--project-id",
        envvar="CVAT_PROJECT_ID",
        help="Default project ID.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug logging.",
    ),
) -> None:
    """Global server connection options (can also be set via environment variables)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj.update(
        {
            "config_file": config_file,
            "url": url,
            "username": username,
            "password": password,
            "project_id": project_id,
        },
    )


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


@app.command()
def download(
    ctx: typer.Context,
    task_id: Optional[List[int]] = typer.Option(
        None,
        "--task-id",
        "-t",
        help="Task ID to download. Repeat for multiple tasks.",
    ),
    out_dir: Optional[str] = typer.Option(
        None,
        "--out-dir",
        "-o",
        help="Output directory. Tasks are saved as task{id}/ subdirs.",
    ),
    out_path: Optional[List[str]] = typer.Option(
        None,
        "--out-path",
        help="Explicit output path per task (repeat to match --task-id count).",
    ),
    fmt: str = typer.Option(
        DatasetFormat.CVAT.value,
        "--format",
        "-f",
        help="Annotation format: 'CVAT for images 1.1' or 'COCO 1.0'.",
    ),
    save_images: bool = typer.Option(
        False,
        "--save-images/--no-save-images",
        help="Also download images.",
    ),
    skip_existing: bool = typer.Option(
        True,
        "--skip-existing/--no-skip-existing",
        help="Skip tasks already on disk.",
    ),
    folder_prefix: Optional[str] = typer.Option(
        None,
        "--folder-prefix",
        help="Output folder prefix per task. Default 'task' gives task147/; set 'data_' to get data_147/.",
    ),
) -> None:
    """Download annotations (and optionally images) from CVAT tasks."""
    if not task_id:
        console.print("[red]Error:[/red] Provide at least one --task-id / -t.")
        raise typer.Exit(code=1)
    if not out_dir and not out_path:
        console.print("[red]Error:[/red] Provide --out-dir or --out-path.")
        raise typer.Exit(code=1)

    try:
        dataset_format = DatasetFormat(fmt)
    except ValueError:
        console.print(
            f"[red]Error:[/red] Unknown format '{fmt}'. Use 'COCO 1.0' or 'CVAT for images 1.1'.",
        )
        raise typer.Exit(code=1)

    client = _make_client(ctx)
    console.print(f"Downloading {len(task_id)} task(s) ...")
    client.download_tasks(
        task_ids=list(task_id),
        out_dir=out_dir,
        out_paths=[Path(p) for p in out_path] if out_path else None,
        fmt=dataset_format,
        save_images=save_images,
        skip_existing=skip_existing,
        folder_prefix=folder_prefix or "task",
    )
    console.print("[green]Done.[/green]")


# ---------------------------------------------------------------------------
# upload
# ---------------------------------------------------------------------------


@app.command()
def upload(
    ctx: typer.Context,
    task_id: Optional[List[int]] = typer.Option(
        None,
        "--task-id",
        "-t",
        help="Task ID to upload to. Repeat for multiple tasks.",
    ),
    in_dir: Optional[str] = typer.Option(
        None,
        "--in-dir",
        "-i",
        help="Input directory containing task{id}/ subdirs with annotation files.",
    ),
    fmt: str = typer.Option(
        DatasetFormat.CVAT.value,
        "--format",
        "-f",
        help="Annotation format: 'CVAT for images 1.1' or 'COCO 1.0'.",
    ),
) -> None:
    """Upload local annotations to CVAT tasks.

      Expects annotation files at:
        - COCO:  <in_dir>/task{id}/annotations/instances_default_pseudo.json
    (falls back to instances_default.json)
        - CVAT:  <in_dir>/task{id}/annotations_pseudo.xml
    (falls back to annotations.xml)
    """
    if not task_id:
        console.print("[red]Error:[/red] Provide at least one --task-id / -t.")
        raise typer.Exit(code=1)
    if not in_dir:
        console.print("[red]Error:[/red] Provide --in-dir.")
        raise typer.Exit(code=1)

    try:
        dataset_format = DatasetFormat(fmt)
    except ValueError:
        console.print(f"[red]Error:[/red] Unknown format '{fmt}'.")
        raise typer.Exit(code=1)

    client = _make_client(ctx)
    console.print(f"Uploading {len(task_id)} task(s) ...")
    client.upload_tasks(list(task_id), in_dir, dataset_format)
    console.print("[green]Done.[/green]")


# ---------------------------------------------------------------------------
# list-tasks
# ---------------------------------------------------------------------------


@app.command(name="list-tasks")
def list_tasks(
    ctx: typer.Context,
    project_id: Optional[int] = typer.Option(
        None,
        "--project-id",
        help="Filter by project ID.",
    ),
    output_fmt: str = typer.Option(
        "table",
        "--output",
        help="Output format: table or json.",
    ),
) -> None:
    """List CVAT tasks accessible to the authenticated user."""
    client = _make_client(ctx)
    tasks = client.get_tasks(project_id)

    if output_fmt == "json":
        console.print_json(json.dumps(tasks, indent=2))
        return

    table = Table(
        title=f"Tasks (project_id={project_id or client.project_id or 'all'})",
    )
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Status", style="green")
    table.add_column("Size", justify="right")
    table.add_column("Mode")

    for t in tasks:
        table.add_row(
            str(t.get("id", "")),
            t.get("name", ""),
            t.get("status", ""),
            str(t.get("size", "")),
            t.get("mode", ""),
        )

    console.print(table)
    console.print(f"Total: {len(tasks)} task(s)")


# ---------------------------------------------------------------------------
# list-projects
# ---------------------------------------------------------------------------


@app.command(name="list-projects")
def list_projects(
    ctx: typer.Context,
    output_fmt: str = typer.Option(
        "table",
        "--output",
        help="Output format: table or json.",
    ),
) -> None:
    """List CVAT projects accessible to the authenticated user."""
    client = _make_client(ctx)
    projects = client.get_projects()

    if output_fmt == "json":
        console.print_json(json.dumps(projects, indent=2))
        return

    table = Table(title="Projects")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Status", style="green")
    table.add_column("Owner")
    table.add_column("Task count", justify="right")

    for p in projects:
        owner = p.get("owner") or {}
        table.add_row(
            str(p.get("id", "")),
            p.get("name", ""),
            p.get("status", ""),
            owner.get("username", ""),
            str(p.get("tasks_count", p.get("task_count", ""))),
        )

    console.print(table)
    console.print(f"Total: {len(projects)} project(s)")


# ---------------------------------------------------------------------------
# task-info
# ---------------------------------------------------------------------------


@app.command(name="task-info")
def task_info(
    ctx: typer.Context,
    task_id: Optional[List[int]] = typer.Option(
        None,
        "--task-id",
        "-t",
        help="Task ID. Repeat for multiple tasks.",
    ),
    output_fmt: str = typer.Option(
        "table",
        "--output",
        help="Output format: table or json.",
    ),
) -> None:
    """Show detailed information about one or more tasks."""
    if not task_id:
        console.print("[red]Error:[/red] Provide at least one --task-id / -t.")
        raise typer.Exit(code=1)

    client = _make_client(ctx)
    infos = []
    for tid in task_id:
        try:
            infos.append(client.get_task_info(tid))
        except Exception as exc:
            console.print(f"[red]Error fetching task {tid}:[/red] {exc}")

    if output_fmt == "json":
        console.print_json(json.dumps(infos, indent=2))
        return

    for info in infos:
        labels = ", ".join(lb["name"] for lb in info.get("labels", []) if "name" in lb) or "—"
        console.print(
            f"\n[bold cyan]Task {info.get('id')}[/bold cyan]: {info.get('name', '')}",
        )
        console.print(f"  Status    : {info.get('status', '')}")
        console.print(f"  Size      : {info.get('size', '')} frame(s)")
        console.print(f"  Mode      : {info.get('mode', '')}")
        console.print(f"  Project   : {info.get('project_id', '')}")
        console.print(f"  Labels    : {labels}")
        console.print(f"  Created   : {info.get('created_date', '')}")
        console.print(f"  Updated   : {info.get('updated_date', '')}")


# ---------------------------------------------------------------------------
# check-connection
# ---------------------------------------------------------------------------


@app.command(name="check-connection")
def check_connection(ctx: typer.Context) -> None:
    """Verify that the server credentials are correct and the server is reachable."""
    client = _make_client(ctx)
    if client.check_connection():
        console.print("[green]Connection OK.[/green]")
    else:
        console.print("[red]Connection FAILED.[/red] Check your URL and credentials.")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# run (YAML-driven)
# ---------------------------------------------------------------------------

_TASK_ALIASES: dict[str, str] = {
    "download_cvat_tasks": "download",
    "upload_anno_with_cvat_tasks": "upload",
}


def _client_from_yaml_or_ctx(config_entry: dict, ctx_obj: dict) -> CVATClient:
    server_block = config_entry.get("server")
    if server_block:
        cfg = ServerConfig(**server_block)
    else:
        cfg = _resolve_server_config(
            ctx_obj.get("config_file"),
            ctx_obj.get("url"),
            ctx_obj.get("username"),
            ctx_obj.get("password"),
            ctx_obj.get("project_id"),
        )
    return CVATClient.from_config(cfg)


@app.command()
def run(
    ctx: typer.Context,
    yaml_file: str = typer.Argument(..., help="Path to YAML configuration file."),
) -> None:
    """Run CVAT operations defined in a YAML configuration file.

    Supported task names:

    \b
      download_cvat_tasks         — download tasks
      upload_anno_with_cvat_tasks — upload annotations

    Example YAML:

    \b
      - task: download_cvat_tasks
        parameters:
          task_ids: [147, 150]
          out_dir: data/raw
          dataset_format: "CVAT for images 1.1"
          save_images: false
    """
    with open(yaml_file) as fh:
        configs = yaml.safe_load(fh)

    if not configs:
        console.print("[yellow]Warning:[/yellow] YAML file is empty, nothing to do.")
        return

    # Pre-flight: verify connectivity and project before doing any work
    preflight_client = _client_from_yaml_or_ctx(configs[0], ctx.obj or {})
    console.print("Checking CVAT connection ...")
    if not preflight_client.check_connection():
        console.print(
            "[red]Error:[/red] Cannot connect to CVAT server. Check URL and credentials."
        )
        raise typer.Exit(code=1)
    console.print(f"  [green]✓[/green] Connected to {preflight_client.url}")

    if preflight_client.project_id:
        console.print(f"Checking project {preflight_client.project_id} ...")
        if not preflight_client.check_project():
            console.print(
                f"[red]Error:[/red] Project {preflight_client.project_id} not found or not accessible.",
            )
            raise typer.Exit(code=1)
        console.print(f"  [green]✓[/green] Project {preflight_client.project_id} OK")

    def _make_progress() -> Progress:
        return Progress(
            TextColumn("  [cyan]{task.description}[/cyan]"),
            BarColumn(bar_width=None),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        )

    for entry in configs:
        task_name = entry.get("task", "")
        canonical = _TASK_ALIASES.get(task_name, task_name)
        params: dict = entry.get("parameters", {}) or {}
        client = _client_from_yaml_or_ctx(entry, ctx.obj or {})

        fmt_str = params.get("dataset_format", DatasetFormat.CVAT.value)
        try:
            fmt = DatasetFormat(fmt_str)
        except ValueError:
            logger.error("Unknown format '%s' in task '%s'", fmt_str, task_name)
            continue

        errors: list[tuple[int, str]] = []

        if canonical == "download":
            task_ids: list[int] = params.get("task_ids", [])
            out_dir = params.get("out_dir")
            out_paths_raw = params.get("out_paths")
            if not out_dir and not out_paths_raw:
                logger.error("Task '%s': provide out_dir or out_paths", task_name)
                continue
            folder_prefix: str = params.get("folder_prefix", "task")
            paths = (
                [Path(p) for p in out_paths_raw]
                if out_paths_raw
                else [Path(out_dir) / f"{folder_prefix}{tid}" for tid in task_ids]
            )
            save_images: bool = params.get("save_images", False)
            skip_existing: bool = params.get("skip_existing", True)

            console.print(f"[bold]download[/bold] — {len(task_ids)} task(s)")
            with _make_progress() as progress:
                bar = progress.add_task("starting", total=len(task_ids))
                for tid, dest in zip(task_ids, paths):
                    progress.update(bar, description=f"task {tid}")
                    if skip_existing and client._has_annotations(dest, fmt):
                        logger.debug("Task %s: already exists, skipping", tid)
                        progress.advance(bar)
                        continue
                    try:
                        client.download_annotations(tid, dest, fmt, save_images)
                    except Exception as exc:
                        errors.append((tid, str(exc)))
                    progress.advance(bar)

        elif canonical == "upload":
            per_task = params.get("tasks")
            if per_task:
                console.print(f"[bold]upload[/bold] — {len(per_task)} task(s)")
                with _make_progress() as progress:
                    bar = progress.add_task("starting", total=len(per_task))
                    for item in per_task:
                        tid = item.get("task_id")
                        anno_path = item.get("annotation_path")
                        if tid is None or not anno_path:
                            errors.append((tid or 0, "missing task_id or annotation_path"))
                            progress.advance(bar)
                            continue
                        item_fmt_str = item.get("dataset_format", fmt_str)
                        try:
                            item_fmt = DatasetFormat(item_fmt_str)
                        except ValueError:
                            errors.append((int(tid), f"unknown format '{item_fmt_str}'"))
                            progress.advance(bar)
                            continue
                        progress.update(bar, description=f"task {tid}")
                        try:
                            ok = client.upload_annotations(int(tid), Path(anno_path), item_fmt)
                            if not ok:
                                errors.append((int(tid), "upload returned failure"))
                        except Exception as exc:
                            errors.append((int(tid), str(exc)))
                        progress.advance(bar)
            else:
                task_ids = params.get("task_ids", [])
                in_dir = params.get("in_dir", "")
                console.print(f"[bold]upload[/bold] — {len(task_ids)} task(s)")
                with _make_progress() as progress:
                    bar = progress.add_task("starting", total=len(task_ids))
                    for tid in task_ids:
                        progress.update(bar, description=f"task {tid}")
                        task_dir = Path(in_dir) / f"task{tid}"
                        candidates = (
                            [
                                task_dir / "annotations" / "instances_default_pseudo.json",
                                task_dir / "annotations" / "instances_default.json",
                            ]
                            if fmt == DatasetFormat.COCO
                            else [
                                task_dir / "annotations_pseudo.xml",
                                task_dir / "annotations.xml",
                            ]
                        )
                        anno_file = next((c for c in candidates if c.exists()), None)
                        if anno_file is None:
                            errors.append((tid, f"no annotation file in {task_dir}"))
                            progress.advance(bar)
                            continue
                        try:
                            ok = client.upload_annotations(tid, anno_file, fmt)
                            if not ok:
                                errors.append((tid, "upload returned failure"))
                        except Exception as exc:
                            errors.append((tid, str(exc)))
                        progress.advance(bar)
        else:
            console.print(f"[yellow]Unknown task:[/yellow] '{task_name}', skipping.")
            continue

        if errors:
            console.print(f"  [red]✗ {len(errors)} task(s) failed:[/red]")
            for tid, err in errors:
                logger.error("task %s: %s", tid, err)
        else:
            logger.info("%s — all tasks completed", canonical)

    console.print("[green]All done.[/green]")


def main_cli() -> None:
    app()


if __name__ == "__main__":
    main_cli()
