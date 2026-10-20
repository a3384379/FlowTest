from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

AssetPublication = Literal["published", "unpublished"]
AssetResult = Literal["unrun", "queued", "running", "passed", "failed", "cancelled", "quarantined"]
AssetCatalogOrder = Literal["updated_desc", "name_asc", "name_desc", "latest_run_desc"]


class InvalidAssetCatalogScope(ValueError):
    """An asset catalog filter is outside the supported query contract."""


@dataclass(frozen=True, slots=True)
class AssetCatalogScope:
    publication: AssetPublication | None = None
    latest_result: AssetResult | None = None
    environment_id: UUID | None = None
    order: AssetCatalogOrder = "updated_desc"

    def validated(self) -> "AssetCatalogScope":
        _validate_choice(self.publication, frozenset({"published", "unpublished"}), "发布状态")
        _validate_choice(
            self.latest_result,
            frozenset(
                {"unrun", "queued", "running", "passed", "failed", "cancelled", "quarantined"}
            ),
            "最近运行结果",
        )
        _validate_choice(
            self.order,
            frozenset({"updated_desc", "name_asc", "name_desc", "latest_run_desc"}),
            "排序方式",
            required=True,
        )
        return self


def _validate_choice(
    value: str | None, supported: frozenset[str], label: str, *, required: bool = False
) -> None:
    if (required and value is None) or (value is not None and value not in supported):
        raise InvalidAssetCatalogScope(f"不支持的{label}")


@dataclass(frozen=True, slots=True)
class AssetCatalogRun:
    status: str
    occurred_at: datetime
    execution_id: UUID | None
    plan_id: UUID | None
    plan_run_id: UUID | None
    asset_version: int | None
    source: Literal["direct", "plan"]


@dataclass(frozen=True, slots=True)
class AssetCatalogEnvironment:
    id: UUID
    name: str
