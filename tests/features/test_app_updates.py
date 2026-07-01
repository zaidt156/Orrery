import json

from backend.features import app_updates


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_version_compare_handles_v_prefix():
    assert app_updates.is_newer("v0.1.4", "0.1.3") is True
    assert app_updates.is_newer("v0.1.3", "0.1.3") is False
    assert app_updates.is_newer("v0.1.2", "0.1.3") is False


def test_update_check_sanitizes_release_payload(monkeypatch):
    def fake_urlopen(_request, timeout):
        assert timeout == 6.0
        return _Response({
            "tag_name": "v0.1.4",
            "name": "Orrery v0.1.4",
            "html_url": "https://github.com/zaidt156/Orrery/releases/tag/v0.1.4",
            "published_at": "2026-07-01T20:00:00Z",
            "assets": [
                {"name": "Orrery-Windows.zip", "browser_download_url": "https://example.com/win.zip", "size": 123},
                {"name": "bad", "browser_download_url": None, "size": None},
            ],
        })

    monkeypatch.setattr(app_updates.urllib.request, "urlopen", fake_urlopen)

    result = app_updates.check_for_updates()

    assert result["ok"] is True
    assert result["latest_version"] == "0.1.4"
    assert result["update_available"] is True
    assert result["assets"][0]["name"] == "Orrery-Windows.zip"
    assert result["assets"][1]["url"] == ""
