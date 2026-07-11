import pytest

from backend.features import filegen, taskrouter


@pytest.mark.parametrize(
    "extension",
    [
        "pdf", "docx", "xlsx", "pptx", "csv", "tex", "png", "jpg", "gif", "webp",
        "svg", "wav", "mp3", "mp4", "webm", "zip", "html", "md", "txt", "json",
    ],
)
def test_explicit_output_extension_routes_to_file_generation(extension):
    request = f"Create five simple .{extension} files"

    assert filegen.wants_file(request), request
    assert taskrouter.plan(request).route == "file", request
