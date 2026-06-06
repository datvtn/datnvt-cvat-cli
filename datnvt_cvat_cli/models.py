from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DatasetFormat(str, Enum):
    COCO = "COCO 1.0"
    CVAT = "CVAT for images 1.1"


# Query string used by the CVAT API differs from the enum value in some endpoints
DATASET_FORMAT_QUERY_MAP: dict[DatasetFormat, str] = {
    DatasetFormat.COCO: "COCO 1.0",
    DatasetFormat.CVAT: "CVAT 1.1",
}


class ServerConfig(BaseModel):
    url: str = Field(..., description="CVAT server URL (e.g. https://cvat.example.com)")
    username: str = Field(..., description="CVAT username")
    password: str = Field(..., description="CVAT password", repr=False)
    project_id: int = Field(0, description="Default CVAT project ID")
