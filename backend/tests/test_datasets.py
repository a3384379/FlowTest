import csv
import json
from io import BytesIO, StringIO
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.datasets import DATASET_ROW_LIMIT, DatasetParseError, parse_dataset
from app.engine.contracts import DatasetFormat, WorkflowDefinition
from app.services.datasets import WorkflowDatasetService


def test_csv_dataset_preserves_columns_and_blank_values() -> None:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["username", "enabled"])
    writer.writerow(["alice", "true"])
    writer.writerow(["bob", ""])

    parsed = parse_dataset(
        filename="users.csv",
        content=output.getvalue().encode(),
        requested_format=DatasetFormat.AUTO,
    )

    assert parsed.format is DatasetFormat.CSV
    assert parsed.columns == ("username", "enabled")
    assert parsed.rows[1] == {"username": "bob", "enabled": ""}


def test_json_dataset_requires_consistent_objects() -> None:
    with pytest.raises(DatasetParseError, match="每行字段必须一致"):
        parse_dataset(
            filename="users.json",
            content=json.dumps([{"id": 1}, {"name": "bob"}]).encode(),
            requested_format=DatasetFormat.JSON,
        )


def test_excel_dataset_reads_the_selected_sheet_without_evaluating_formulas() -> None:
    workbook = Workbook()
    active = workbook.active
    active.title = "ignored"
    sheet = workbook.create_sheet("users")
    sheet.append(["id", "name", "formula"])
    sheet.append([7, "alice", "=1+1"])
    output = BytesIO()
    workbook.save(output)

    parsed = parse_dataset(
        filename="users.xlsx",
        content=output.getvalue(),
        requested_format=DatasetFormat.AUTO,
        sheet_name="users",
    )

    assert parsed.format is DatasetFormat.EXCEL
    assert parsed.rows == ({"id": 7, "name": "alice", "formula": None},)


def test_dataset_rejects_more_than_one_thousand_rows() -> None:
    content = json.dumps([{"id": index} for index in range(DATASET_ROW_LIMIT + 1)]).encode()

    with pytest.raises(DatasetParseError, match="最多执行 1000 行"):
        parse_dataset(
            filename="too-many.json",
            content=content,
            requested_format=DatasetFormat.AUTO,
        )


def test_dataset_rejects_unknown_extension() -> None:
    with pytest.raises(DatasetParseError, match="仅支持"):
        parse_dataset(
            filename="users.xls",
            content=b"legacy",
            requested_format=DatasetFormat.AUTO,
        )


@pytest.mark.asyncio
async def test_dataset_preparation_ignores_native_v3_capabilities() -> None:
    definition = WorkflowDefinition.model_validate(
        {
            "schema_version": "1.0",
            "variables": {},
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "name": "开始",
                    "position": {"x": 0, "y": 0},
                    "config": {},
                },
                {
                    "id": "graphql",
                    "type": "capability",
                    "name": "查询用户",
                    "position": {"x": 0, "y": 0},
                    "capability_id": "graphql.request",
                    "capability_version": "3.0.0",
                    "configuration": {
                        "schema_id": str(uuid4()),
                        "endpoint": "https://api.example.com/graphql",
                        "operation": "query { users { id } }",
                    },
                    "bindings": [],
                },
                {
                    "id": "end",
                    "type": "end",
                    "name": "结束",
                    "position": {"x": 400, "y": 0},
                    "config": {},
                },
            ],
            "edges": [
                {"id": "start-graphql", "source": "start", "target": "graphql"},
                {"id": "graphql-end", "source": "graphql", "target": "end"},
            ],
        }
    )
    session = AsyncMock(spec=AsyncSession)

    prepared = await WorkflowDatasetService(session).prepare(
        project_id=uuid4(),
        definition=definition,
    )

    assert prepared is None
