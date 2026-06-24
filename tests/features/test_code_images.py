import pytest

from backend.features import code_images


def test_sanitize_svg_keeps_strict_vector_content():
    raw = """
    ```svg
    <svg viewBox="0 0 1200 800">
      <defs><linearGradient id="g"><stop offset="0" stop-color="#123456"/></linearGradient></defs>
      <rect x="0" y="0" width="1200" height="800" fill="url(#g)"/>
      <text x="60" y="90" fill="#ffffff" font-size="42">Hello</text>
    </svg>
    ```
    """

    safe = code_images.sanitize_svg(raw)

    assert safe.startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in safe
    assert 'width="1200"' in safe
    assert "linearGradient" in safe


@pytest.mark.parametrize(
    "raw",
    [
        '<svg><script>alert(1)</script></svg>',
        '<svg onload="alert(1)"><rect width="10" height="10"/></svg>',
        '<svg><image href="https://example.com/a.png"/></svg>',
        '<svg><rect fill="url(https://example.com/a.svg#g)"/></svg>',
        '<!DOCTYPE svg><svg><rect width="10" height="10"/></svg>',
    ],
)
def test_sanitize_svg_rejects_executable_or_external_content(raw):
    with pytest.raises(code_images.UnsafeSvgError):
        code_images.sanitize_svg(raw)


def test_image_prompt_removes_command_prefix():
    assert code_images.image_prompt("/image: Draw a blue circuit") == "Draw a blue circuit"



def test_fallback_svg_is_sanitized_and_prompt_labeled():
    safe = code_images.fallback_svg("draw a clean revenue chart")

    assert safe.startswith("<svg")
    assert "Safe SVG fallback" in safe
    assert "revenue" in safe
