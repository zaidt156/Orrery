from backend.features import taskrouter


def test_routes_plain_chat_to_chat():
    plan = taskrouter.plan("Explain how context windows work")

    assert plan.route == "chat"
    assert plan.output_mode == "chat"


def test_routes_document_to_file_without_sandbox():
    plan = taskrouter.plan("Create a Word document about onboarding")

    assert plan.route == "file"
    assert plan.output_mode == "file"
    assert not plan.uses_sandbox


def test_routes_computed_visual_file_to_sandbox_file():
    plan = taskrouter.plan("Create a PNG chart from this sales data")

    assert plan.route == "file"
    assert plan.uses_sandbox


def test_routes_standalone_image_to_svg_artifact():
    plan = taskrouter.plan("Draw a clean logo for a data observatory")

    assert plan.route == "image"
    assert plan.output_mode == "artifact"
    assert "image" in plan.skills


def test_routes_voice_to_sandbox_file_generation():
    plan = taskrouter.plan("Create a voice narration for this introduction")

    assert plan.route == "file"
    assert plan.output_mode == "file"
    assert plan.uses_sandbox


def test_routes_video_to_sandbox_file_generation():
    plan = taskrouter.plan("Create a short MP4 video animation for a product launch")

    assert plan.route == "file"
    assert plan.output_mode == "file"
    assert plan.uses_sandbox


def test_routes_latex_to_sandbox_file_generation():
    plan = taskrouter.plan("Create a LaTeX resume template")

    assert plan.route == "file"
    assert plan.output_mode == "file"
    assert plan.uses_sandbox


def test_routes_project_workspace_requests():
    plan = taskrouter.plan("Create a new project workspace for the Acme rollout")

    assert plan.route == "project"
    assert "project" in plan.skills


def test_routes_described_small_app_to_sandbox_bundle():
    plan = taskrouter.plan("Build me a small expense-splitter app")

    assert plan.route == "file"
    assert plan.output_mode == "file"
    assert plan.uses_sandbox
