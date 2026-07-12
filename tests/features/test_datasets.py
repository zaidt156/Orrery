import asyncio
import uuid

import pytest

from backend.features import datasets


if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.mark.anyio
async def test_reuploading_same_file_replaces_its_dataset_registry_entry():
    token = uuid.uuid4().hex
    filename = f"dataset-reupload-{token}.csv"
    created_ids: set[str] = set()

    try:
        first = await datasets.create_from_file(
            "Initial label",
            filename,
            "order_id,status\n1,open\n",
        )
        created_ids.add(first["id"])

        second = await datasets.create_from_file(
            "Updated label",
            filename,
            "order_id,status\n1,closed\n2,open\n",
        )
        created_ids.add(second["id"])

        matching = [
            row for row in await datasets.list_datasets()
            if row["schema"] == datasets.SCHEMA
            and row["kind"] == "file"
            and row["source"] == filename
        ]
        assert second["id"] == first["id"]
        assert second["table"] == first["table"]
        assert second["name"] == "Updated label"
        assert second["rows"] == 2
        assert len(matching) == 1
    finally:
        for row in await datasets.list_datasets():
            if row["id"] in created_ids or row["source"] == filename:
                await datasets.delete_dataset(row["id"])


@pytest.mark.anyio
async def test_same_dataset_name_with_different_files_remains_distinct():
    token = uuid.uuid4().hex
    filenames = {f"dataset-a-{token}.csv", f"dataset-b-{token}.csv"}
    created_ids: set[str] = set()

    try:
        for filename in filenames:
            row = await datasets.create_from_file(
                "Shared display name",
                filename,
                "order_id,status\n1,open\n",
            )
            created_ids.add(row["id"])

        matching = [
            row for row in await datasets.list_datasets()
            if row["schema"] == datasets.SCHEMA
            and row["kind"] == "file"
            and row["source"] in filenames
        ]
        assert len(matching) == 2
        assert len({row["id"] for row in matching}) == 2
    finally:
        for row in await datasets.list_datasets():
            if row["id"] in created_ids or row["source"] in filenames:
                await datasets.delete_dataset(row["id"])
