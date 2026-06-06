# datnvt-cvat-cli

A focused CLI tool and Python library for managing annotations on a [CVAT](https://www.cvat.ai/) server.

## Features

| Feature | CLI command | Python API |
|---|---|---|
| Download annotations (without images) | `datnvt-cvat-cli download` | `client.download_tasks(...)` |
| Download full dataset (annotations + images) | `datnvt-cvat-cli download --save-images` | `client.download_tasks(..., save_images=True)` |
| Upload annotations to CVAT tasks | `datnvt-cvat-cli upload` | `client.upload_tasks(...)` |
| List tasks for a project | `datnvt-cvat-cli list-tasks` | `client.get_tasks(...)` |
| List all projects | `datnvt-cvat-cli list-projects` | `client.get_projects()` |
| Inspect task metadata | `datnvt-cvat-cli task-info` | `client.get_task_info(task_id)` |
| Verify server credentials | `datnvt-cvat-cli check-connection` | `client.check_connection()` |
| Check project availability | — | `client.check_project(project_id)` |
| Run batch operations from YAML | `datnvt-cvat-cli run config.yaml` | — |

## Installation

```bash
pip install datnvt-cvat-cli
```

Or from source:

```bash
git clone https://github.com/datvtn/datnvt-cvat-cli.git
cd datnvt-cvat-cli
pip install -e .
```

Requires Python ≥ 3.9.

## Configuration

Server credentials can be supplied in three ways (highest priority first):

### 1. CLI flags

```bash
datnvt-cvat-cli --url https://cvat.example.com \
         --username myuser \
         --password mypassword \
         --project-id 11 \
         list-tasks
```

### 2. YAML config file

```yaml
# config/server.yaml
url: "https://cvat.example.com"
username: "myuser"
password: "mypassword"
project_id: 11
```

```bash
datnvt-cvat-cli --config config/server.yaml list-tasks
# or
export CVAT_SERVER_CONFIG=config/server.yaml
datnvt-cvat-cli list-tasks
```

### 3. Environment variables

```bash
export CVAT_URL=https://cvat.example.com
export CVAT_USERNAME=myuser
export CVAT_PASSWORD=mypassword
export CVAT_PROJECT_ID=11
```

---

## CLI Reference

### Global options (apply to all commands)

```
datnvt-cvat-cli [OPTIONS] COMMAND [ARGS]

Options:
  --config, -c FILE       Server config YAML  [env: CVAT_SERVER_CONFIG]
  --url TEXT              CVAT server URL     [env: CVAT_URL]
  --username, -u TEXT     CVAT username       [env: CVAT_USERNAME]
  --password, -p TEXT     CVAT password       [env: CVAT_PASSWORD]
  --project-id INTEGER    Default project ID  [env: CVAT_PROJECT_ID]
  --verbose, -v           Enable debug logging
```

---

### `download` — Download CVAT tasks

Downloads annotations (and optionally images) for one or more tasks.

```
datnvt-cvat-cli download [OPTIONS]

Options:
  --task-id, -t INTEGER    Task ID (repeat for multiple)  [required]
  --out-dir, -o PATH       Output directory; tasks saved as task{id}/ subdirs
  --out-path PATH          Explicit output path per task (repeat to match --task-id)
  --format, -f TEXT        Annotation format [default: CVAT for images 1.1]
  --save-images / --no-save-images
                           Also download raw images [default: no-save-images]
  --skip-existing / --no-skip-existing
                           Skip tasks already on disk [default: skip-existing]
  --folder-prefix TEXT     Output folder prefix per task [default: task]
                           e.g. --folder-prefix data_ → data_147/ instead of task147/
```

**Supported formats:**
- `CVAT for images 1.1` (XML, **default**)
- `COCO 1.0` (JSON)

**Output structure (CVAT format, default):**
```
out_dir/
  task147/
    annotations.xml
    images/          ← only when --save-images
      frame_000001.jpg
      ...
  task150/
    annotations.xml
```

**Examples:**

```bash
# Download annotations only for tasks 147 and 150
datnvt-cvat-cli --config server.yaml download -t 147 -t 150 --out-dir data/raw

# Download with images (default CVAT XML format)
datnvt-cvat-cli --config server.yaml download -t 147 --out-dir data/raw --save-images

# Download as COCO JSON instead
datnvt-cvat-cli --config server.yaml download -t 147 --out-dir data/raw \
         --format "COCO 1.0"

# Force re-download even if files exist
datnvt-cvat-cli --config server.yaml download -t 147 --out-dir data/raw --no-skip-existing

# Rename output folders: data_147/ instead of task147/
datnvt-cvat-cli --config server.yaml download -t 147 -t 150 --out-dir data/raw \
         --folder-prefix data_

# Custom output path per task
datnvt-cvat-cli --config server.yaml download -t 147 -t 150 \
         --out-path data/task_a --out-path data/task_b
```

---

### `upload` — Upload annotations to CVAT

Pushes local annotation files to the corresponding CVAT tasks.

```
datnvt-cvat-cli upload [OPTIONS]

Options:
  --task-id, -t INTEGER    Task ID (repeat for multiple)  [required]
  --in-dir, -i PATH        Input directory containing task{id}/ subdirs  [required]
  --format, -f TEXT        Annotation format [default: CVAT for images 1.1]
```

**File lookup (in order of preference):**

| Format | Primary | Fallback |
|--------|---------|----------|
| CVAT 1.1 | `<in_dir>/task{id}/annotations_pseudo.xml` | `annotations.xml` |
| COCO 1.0 | `<in_dir>/task{id}/annotations/instances_default_pseudo.json` | `instances_default.json` |

**Examples:**

```bash
# Upload CVAT XML annotations from data/processed/ for tasks 147 and 150 (default format)
datnvt-cvat-cli --config server.yaml upload -t 147 -t 150 --in-dir data/processed

# Upload COCO JSON annotations
datnvt-cvat-cli --config server.yaml upload -t 147 --in-dir data/processed \
         --format "COCO 1.0"
```

---

### `list-tasks` — List tasks

```
datnvt-cvat-cli list-tasks [OPTIONS]

Options:
  --project-id INTEGER     Filter by project ID (defaults to config project_id)
  --output TEXT            Output format: table (default) or json
```

**Examples:**

```bash
# List all tasks in the default project
datnvt-cvat-cli --config server.yaml list-tasks

# List tasks for a specific project in JSON
datnvt-cvat-cli --config server.yaml list-tasks --project-id 15 --output json
```

**Sample output:**
```
              Tasks (project_id=11)
┌──────┬──────────────────────────┬────────────┬───────┬──────────────┐
│ ID   │ Name                     │ Status     │ Size  │ Mode         │
├──────┼──────────────────────────┼────────────┼───────┼──────────────┤
│  147 │ Training batch 1         │ completed  │   500 │ annotation   │
│  150 │ Validation set           │ annotation │   200 │ annotation   │
└──────┴──────────────────────────┴────────────┴───────┴──────────────┘
Total: 2 task(s)
```

---

### `list-projects` — List projects

```
datnvt-cvat-cli list-projects [OPTIONS]

Options:
  --output TEXT    Output format: table (default) or json
```

**Examples:**

```bash
datnvt-cvat-cli --config server.yaml list-projects
datnvt-cvat-cli --config server.yaml list-projects --output json
```

---

### `task-info` — Inspect task details

```
datnvt-cvat-cli task-info [OPTIONS]

Options:
  --task-id, -t INTEGER    Task ID (repeat for multiple)  [required]
  --output TEXT            Output format: table (default) or json
```

**Examples:**

```bash
# Show details for tasks 147 and 150
datnvt-cvat-cli --config server.yaml task-info -t 147 -t 150

# Get raw JSON for task 147
datnvt-cvat-cli --config server.yaml task-info -t 147 --output json
```

**Sample output:**
```
Task 147: Training batch 1
  Status    : completed
  Size      : 500 frame(s)
  Mode      : annotation
  Project   : 11
  Labels    : door, window, wall
  Created   : 2024-01-10T09:00:00Z
  Updated   : 2024-03-15T14:22:00Z
```

---

### `check-connection` — Verify credentials

```bash
datnvt-cvat-cli --config server.yaml check-connection
# Connection OK.
```

---

### `run` — Batch operations from YAML

Run multiple operations defined in a single YAML file. Before executing any tasks, `run` performs **pre-flight checks**: it verifies the CVAT server is reachable and that the configured project is accessible. The run aborts with a non-zero exit code if either check fails.

```bash
datnvt-cvat-cli --config server.yaml run config/cvat/tasks.yaml
# or embed server credentials directly in the YAML (see format below)
datnvt-cvat-cli run config/cvat/tasks.yaml
```

**Supported task names:**

| YAML task name | Operation |
|---|---|
| `download_cvat_tasks` | Download annotations (and optionally images) |
| `upload_anno_with_cvat_tasks` | Upload local annotations to CVAT |

---

## YAML Configuration Files

### Download — `config/download.yaml`

```yaml
# Download annotations (and optionally images) for a list of tasks.
# Run with: datnvt-cvat-cli --config server.yaml run config/download.yaml

- task: download_cvat_tasks
  parameters:
    # List of CVAT task IDs to download.
    task_ids: [147, 150, 151]

    # Output directory. Each task is saved under <out_dir>/task{id}/.
    out_dir: data/raw

    # Annotation format: "CVAT for images 1.1" (XML, default) or "COCO 1.0" (JSON).
    dataset_format: "CVAT for images 1.1"

    # Set true to also download the raw image files alongside annotations.
    save_images: false

    # Set false to force re-download even when annotation files already exist.
    skip_existing: true

    # Optional: rename output folders using a custom prefix instead of "task".
    # Default: task147/, task150/, ...  |  "data_" → data_147/, data_150/, ...
    # folder_prefix: "data_"
```

Output layout for CVAT XML format (default):
```
data/raw/
  task147/
    annotations.xml
    images/           ← only when save_images: true
  task150/
    annotations.xml
```

Output layout for COCO JSON format:
```
data/raw/
  task147/
    annotations/
      instances_default.json
    images/           ← only when save_images: true
```

---

### Upload — `config/upload.yaml`

Each task specifies its own annotation file path. The format can be set globally and overridden per task.

```yaml
# Upload annotation files to CVAT — one explicit path per task.
# Run with: datnvt-cvat-cli --config server.yaml run config/upload.yaml

- task: upload_anno_with_cvat_tasks
  parameters:
    # Default annotation format for all tasks below.
    # Can be overridden individually with a "dataset_format" key on any task entry.
    dataset_format: "CVAT for images 1.1"   # "CVAT for images 1.1" (default) or "COCO 1.0"

    tasks:
      - task_id: 147
        annotation_path: data/processed/task147_annotations.xml

      - task_id: 150
        annotation_path: data/processed/task150_annotations.xml

      # Override format for a single task (COCO JSON instead of CVAT XML)
      - task_id: 151
        annotation_path: data/processed/task151_annotations.json
        dataset_format: "COCO 1.0"
```

**Directory-convention fallback** — if you prefer the auto-resolved path layout, omit `tasks` and use `in_dir` instead:

```yaml
- task: upload_anno_with_cvat_tasks
  parameters:
    task_ids: [147, 150, 151]
    in_dir: data/processed      # looks for task{id}/ subdirs
    dataset_format: "CVAT for images 1.1"
    # CVAT: <in_dir>/task{id}/annotations_pseudo.xml
    #        (falls back to annotations.xml)
    # COCO: <in_dir>/task{id}/annotations/instances_default_pseudo.json
    #        (falls back to instances_default.json)
```

---

### Combined download + upload — `config/tasks.yaml`

```yaml
# Run both download and upload steps in sequence.
# Run with: datnvt-cvat-cli --config server.yaml run config/tasks.yaml
#
# To embed server credentials directly (overrides --config / env vars),
# add a "server" key to any entry:
#
# - task: download_cvat_tasks
#   server:
#     url: "https://cvat.example.com"
#     username: "myuser"
#     password: "mypassword"
#     project_id: 11
#   parameters:
#     ...

# Step 1: download existing annotations from CVAT
- task: download_cvat_tasks
  parameters:
    task_ids: [147, 150, 151]
    out_dir: data/raw
    dataset_format: "CVAT for images 1.1"
    save_images: false
    skip_existing: true

# Step 2: upload revised annotations back to CVAT (per-task explicit paths)
- task: upload_anno_with_cvat_tasks
  parameters:
    dataset_format: "CVAT for images 1.1"
    tasks:
      - task_id: 147
        annotation_path: data/processed/task147_annotations.xml
      - task_id: 150
        annotation_path: data/processed/task150_annotations.xml
      - task_id: 151
        annotation_path: data/processed/task151_annotations.xml
```

---

## Python API

```python
from datnvt_cvat_cli import CVATClient, DatasetFormat, ServerConfig

# Instantiate
client = CVATClient(
    url="https://cvat.example.com",
    username="myuser",
    password="mypassword",
    project_id=11,
)

# Or from a ServerConfig object
cfg = ServerConfig(url="...", username="...", password="...", project_id=11)
client = CVATClient.from_config(cfg)

# Pre-flight checks
ok = client.check_connection()          # True if server is reachable and credentials valid
ok = client.check_project()             # True if client.project_id is accessible
ok = client.check_project(project_id=5) # check a specific project

# List projects / tasks
projects = client.get_projects()          # list[dict]
tasks    = client.get_tasks()             # all tasks in default project
tasks    = client.get_tasks(project_id=15)
task_ids = client.get_task_ids()          # list[int]

# Get task metadata
info = client.get_task_info(task_id=147)

# Download annotations for multiple tasks (default: CVAT for images 1.1)
client.download_tasks(
    task_ids=[147, 150],
    out_dir="data/raw",
    fmt=DatasetFormat.CVAT,   # default
    save_images=False,
    skip_existing=True,
    folder_prefix="task",     # default; use "data_" to get data_147/ instead of task147/
)

# Download a single task to a specific path
from pathlib import Path
client.download_annotations(
    task_id=147,
    out_path=Path("data/raw/task147"),
    fmt=DatasetFormat.CVAT,
    save_images=True,
)

# Upload annotations for multiple tasks (default: CVAT for images 1.1)
client.upload_tasks(
    task_ids=[147, 150],
    in_dir="data/processed",
    fmt=DatasetFormat.CVAT,   # default
)

# Upload a single annotation file
client.upload_annotations(
    task_id=147,
    anno_path=Path("data/processed/task147/annotations_pseudo.xml"),
    fmt=DatasetFormat.CVAT,
)
```

---

## Environment variables

| Variable | Description |
|---|---|
| `CVAT_SERVER_CONFIG` | Path to server YAML config file |
| `CVAT_URL` | CVAT server URL |
| `CVAT_USERNAME` | CVAT username |
| `CVAT_PASSWORD` | CVAT password |
| `CVAT_PROJECT_ID` | Default project ID |

---

## Annotation file paths

After download the expected file layout is:

**CVAT for images 1.1 (default):**
```
task{id}/
  annotations.xml
  images/           ← only when save_images=True
```

**COCO 1.0:**
```
task{id}/
  annotations/
    instances_default.json
  images/           ← only when save_images=True
```

When uploading, the client looks for `annotations_pseudo.xml` / `instances_default_pseudo.json` first, then falls back to the non-pseudo variants.

---

## License

MIT
