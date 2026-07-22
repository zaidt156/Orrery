import json

from backend.features import app_updates


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n=-1):
        return json.dumps(self.payload).encode("utf-8")


def test_version_compare_handles_v_prefix():
    assert app_updates.is_newer("v0.1.4", "0.1.3") is True
    assert app_updates.is_newer("v0.1.3", "0.1.3") is False
    assert app_updates.is_newer("v0.1.2", "0.1.3") is False


def test_update_check_sanitizes_release_payload(monkeypatch):
    # a release one patch ahead of whatever the current version is — survives version bumps
    parts = app_updates.APP_VERSION.split(".")
    newer = ".".join([*parts[:-1], str(int(parts[-1]) + 1)])

    def fake_urlopen(_request, timeout):
        assert timeout == 6.0
        return _Response({
            "tag_name": f"v{newer}",
            "name": f"Orrery v{newer}",
            "html_url": f"https://github.com/zaidt156/Orrery/releases/tag/v{newer}",
            "published_at": "2026-07-01T20:00:00Z",
            "assets": [
                {"name": "Orrery-Windows.zip", "browser_download_url": "https://example.com/win.zip", "size": 123},
                {"name": "bad", "browser_download_url": None, "size": None},
            ],
        })

    monkeypatch.setattr(app_updates.urllib.request, "urlopen", fake_urlopen)

    result = app_updates.check_for_updates()

    assert result["ok"] is True
    assert result["latest_version"] == newer
    assert result["update_available"] is True
    assert result["assets"][0]["name"] == "Orrery-Windows.zip"
    assert result["assets"][1]["url"] == ""
