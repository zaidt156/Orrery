import pytest

from backend.features import artifacts


def test_preview_carries_a_real_download_name():
    """Without a name the viewer saves the file as the uuid in its URL — which is how a generated
    CV once reached the user's disk as 324f1fb3b81345f0ba7247b717ada9d2.pdf."""
    artifact_id = artifacts.register(b"%PDF-1.4", "application/pdf", filename="jordan-rivera-cv.pdf")

    media_type, data, filename = artifacts.get(artifact_id)

    assert media_type == "application/pdf"
    assert data == b"%PDF-1.4"
    assert filename == "jordan-rivera-cv.pdf"


def test_preview_without_a_name_stays_none():
    media_type, data, filename = artifacts.get(artifacts.register("<p>hi</p>"))

    assert media_type == "text/html"
    assert filename is None


@pytest.mark.parametrize(
    "hostile",
    [
        'a"; attachment; filename="evil.exe',  # escape the quoted string
        "x\r\nSet-Cookie: session=stolen",  # CRLF header injection
        "y\nX-Injected: 1",  # bare LF
        "../../etc/passwd",  # traversal
        "\x00null.pdf",  # NUL
    ],
)
def test_download_name_can_never_author_a_header(hostile):
    """The name is interpolated into Content-Disposition, so it must not carry quotes or newlines."""
    _media, _data, filename = artifacts.get(
        artifacts.register(b"x", "application/pdf", filename=hostile)
    )

    assert filename is not None
    assert not {'"', "\r", "\n", "\x00"} & set(filename)
    assert ".." not in filename


def test_download_name_is_bounded():
    _media, _data, filename = artifacts.get(
        artifacts.register(b"x", "application/pdf", filename="a" * 500 + ".pdf")
    )

    assert len(filename) <= 120
