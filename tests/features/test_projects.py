from backend.features import projects


def test_project_text_cleaning_limits_and_collapses_name():
    assert projects._clean("  Acme   rollout  ", 160) == "Acme rollout"
    assert len(projects._clean("x" * 200, 20)) == 20


def test_project_multiline_cleaning_preserves_lines():
    text = projects._clean_multiline(" first  \nsecond\t\n\n", 200)

    assert text == "first\nsecond"


def test_project_constants_are_bounded_for_prompt_safety():
    assert projects.MAX_NAME <= 200
    assert projects.MAX_DESCRIPTION <= 4_000
    assert projects.MAX_INSTRUCTIONS <= 10_000


def test_project_name_from_prompt_requires_clear_create_intent():
    assert projects.name_from_prompt("Create a new project workspace for the Acme rollout") == "Acme rollout"
    assert projects.name_from_prompt("Open the Acme project") is None
