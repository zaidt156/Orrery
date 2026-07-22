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


# --- dataset API URLs never persist credentials (TODO P0) ---

def test_split_secret_url_masks_key_params():
    full, display = datasets._split_secret_url(
        "https://api.example.com/v1/data?limit=5&api_key=SEKRIT"
    )
    assert full == "https://api.example.com/v1/data?limit=5&api_key=SEKRIT"
    assert "SEKRIT" not in display
    assert "limit=5" in display


def test_split_secret_url_leaves_clean_urls_alone():
    url = "https://api.example.com/v1/data?limit=5&page=2"
    assert datasets._split_secret_url(url) == (url, url)


@pytest.mark.anyio
async def test_api_dataset_key_param_goes_to_keychain_not_the_db(monkeypatch):
    from backend.security import secrets

    fetched = []

    async def fake_fetch(url, headers):
        fetched.append(url)
        return ["a"], [["1"]]

    monkeypatch.setattr(datasets, "_fetch_api", fake_fetch)
    url = f"https://api.example.com/data-{uuid.uuid4().hex[:6]}?api_key=SEKRIT123"
    created = await datasets.create_from_api("Key dataset", url)
    try:
        assert "SEKRIT123" not in created["source"]
        assert "api_key=redacted" in created["source"]
        assert secrets.get_secret(f"dataset_url:{created['id']}") == url
        listed = {row["id"]: row for row in await datasets.list_datasets()}
        assert "SEKRIT123" not in listed[created["id"]]["source"]

        # refresh must fetch the real (keychain) URL, not the redacted display URL
        fetched.clear()
        await datasets.refresh_dataset(created["id"])
        assert fetched == [url]
    finally:
        await datasets.delete_dataset(created["id"])
    assert secrets.get_secret(f"dataset_url:{created['id']}") is None


def test_google_sheet_detection_requires_the_real_host():
    assert datasets._is_google_sheet("https://docs.google.com/spreadsheets/d/abc123/export?format=csv")
    # a URL that merely MENTIONS the sheets host must not take the relaxed sheets fetch path
    assert not datasets._is_google_sheet("https://attacker.example/feed?ref=docs.google.com/spreadsheets")
    assert not datasets._is_google_sheet("https://docs.google.com.evil.example/spreadsheets/d/abc")
    assert not datasets._is_google_sheet("https://docs.google.com/other/path")


def test_split_secret_url_catches_common_secret_names():
    for param in ("pwd", "pass", "jwt", "bearer", "session", "sig", "access_token", "client_secret"):
        _full, display = datasets._split_secret_url(f"https://api.example.com/d?{param}=HUSH&page=1")
        assert "HUSH" not in display, f"{param} leaked into the display URL"
        assert "page=1" in display
