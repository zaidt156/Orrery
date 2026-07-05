"""Heavy end-to-end scenario coverage for chat routing + context handling.

This is the "drive it hard with realistic prompts and context" pass: a broad matrix of prompts
through the pure planner, plus integration scenarios through stream_reply that exercise attachments,
vague-follow-up inheritance, and the vision-never-generates-a-file guarantee. No real model calls —
model streams are mocked — so it is fast and reproducible.
"""
import pytest

from backend.features import chat, taskrouter


# --------------------------------------------------------------------------------------------------
# 1) Pure planner matrix — one realistic prompt per row, asserting the route it must resolve to.
#    Behavior notes baked into expectations:
#    - A concrete file format (pdf/docx/xlsx/pptx/csv/tex/html) OUTRANKS a standalone image request.
#    - "draw/… <visual noun>" without a file verb/format → SVG image route.
#    - Most audio phrasings that name a file-ish noun (voiceover/tts/mp3) become a file; only
#      "read … out loud / aloud" style phrasings hit the dedicated audio branch.
# --------------------------------------------------------------------------------------------------
ROUTE_CASES = [
    # plain chat / Q&A — no artifact intent
    ("explain how photosynthesis works", "chat"),
    ("what is the capital of France?", "chat"),
    ("summarize this article for me", "chat"),
    ("hi", "chat"),
    ("what do you think about this approach?", "chat"),
    ("debug why my python loop is slow", "chat"),
    # file: documents / data / decks / markup
    ("create a PDF invoice for $2,400", "file"),
    ("make me a resume", "file"),
    ("generate an excel spreadsheet of my sales", "file"),
    ("build a powerpoint deck about our roadmap", "file"),
    ("write a latex document for my paper", "file"),
    ("give me a csv of the results", "file"),
    ("make an html landing page for the launch", "file"),
    ("turn this into a Word document", "file"),
    ("create an infographic of the funnel", "file"),   # infographic is a file noun → file, not image
    ("create a diagram of the request flow", "file"),   # create + diagram → file (sandbox path)
    # image: SVG artifact route (visual noun, no file verb/format)
    ("draw a logo for my startup", "image"),
    ("design an icon for the settings screen", "image"),
    ("draw a diagram of the architecture", "image"),    # 'draw' is not a file verb → image
    # audio: delivered as a downloadable audio artifact via the FILE route (there is no separate
    # "audio" route value — see taskrouter.plan's audio branch, which returns route="file")
    ("read this out loud", "file"),
    ("say the summary aloud", "file"),
    # project workspace
    ("start a project for client Acme", "project"),
    ("set up a workspace for this case", "project"),
]


@pytest.mark.parametrize("text, expected", ROUTE_CASES)
def test_planner_route_matrix(text, expected):
    assert taskrouter.plan(text).route == expected, f"{text!r} should route to {expected}"


def test_planner_file_deck_prefers_sandbox_but_plain_doc_does_not():
    # a deck/latex/html benefits from the code path; a plain invoice/resume uses deterministic docgen
    assert taskrouter.plan("build a powerpoint deck about AI").sandbox_preferred is True
    assert taskrouter.plan("write a latex document").sandbox_preferred is True
    assert taskrouter.plan("make me a resume").sandbox_preferred is False
    assert taskrouter.plan("create a PDF invoice").sandbox_preferred is False


def test_planner_ignores_empty_and_whitespace():
    assert taskrouter.plan("").route == "chat"
    assert taskrouter.plan("   \n  ").route == "chat"


# --------------------------------------------------------------------------------------------------
# 2) Integration matrix through stream_reply — records which route handler actually fired.
# --------------------------------------------------------------------------------------------------
def _turn(messages):
    return chat._TurnContext(
        model="openai/test",
        system_prompt=None,
        effort=None,
        project_id=None,
        context_window=chat.DEFAULT_CONTEXT_WINDOW,
        messages=messages,
        title="Test chat",
    )


async def _drive(monkeypatch, user_content, *, attachments=None, history=None):
    """Run one stream_reply turn with all route handlers stubbed; return the list of fired routes."""
    fired = []
    messages = list(history or []) + [{"role": "user", "content": user_content}]

    async def fake_prepare_turn(*a, **k):
        return _turn(messages)

    async def fake_trusted_context(project_id):
        return None

    async def fake_record_plan(*a, **k):
        return "route-1"

    async def fake_route_file(*a, **k):
        fired.append("file")
        a[-1].handled = True
        yield {"status": "file-ran"}

    async def fake_route_image(*a, **k):
        fired.append("image")
        yield {"status": "image-ran"}

    async def fake_route_project(*a, **k):
        fired.append("project")
        yield {"status": "project-ran"}

    async def fake_route_model_reply(*a, **k):
        fired.append("model")
        yield {"done": True}

    monkeypatch.setattr(chat.router, "_prepare_turn", fake_prepare_turn)
    monkeypatch.setattr(chat.project_store, "trusted_context", fake_trusted_context)
    monkeypatch.setattr(chat.route_telemetry, "record_plan", fake_record_plan)
    monkeypatch.setattr(chat.router, "_route_file", fake_route_file)
    monkeypatch.setattr(chat.router, "_route_image", fake_route_image)
    monkeypatch.setattr(chat.router, "_route_project_create", fake_route_project)
    monkeypatch.setattr(chat.router, "_route_model_reply", fake_route_model_reply)

    async for _ in chat.stream_reply("00000000-0000-0000-0000-000000000001",
                                     user_content, attachments=attachments or []):
        pass
    return fired


_IMG = {"kind": "image", "name": "shot.png", "content": "data:image/png;base64,AAAA"}
_CSV = {"kind": "text", "name": "data.csv", "content": "a,b\n1,2\n"}


@pytest.mark.anyio
async def test_plain_file_request_routes_to_file(monkeypatch):
    # file route handles the turn (handled=True) → the model fallback does not also run
    assert await _drive(monkeypatch, "create a PDF invoice for $500") == ["file"]


@pytest.mark.anyio
async def test_plain_question_routes_to_model_only(monkeypatch):
    assert await _drive(monkeypatch, "explain how a hash map works") == ["model"]


@pytest.mark.anyio
async def test_image_attachment_never_generates_file_even_with_file_words(monkeypatch):
    # the strongest case: text explicitly asks for a PDF, but an image is attached → vision/chat only
    assert await _drive(monkeypatch, "generate a PDF report of this", attachments=[_IMG]) == ["model"]


@pytest.mark.anyio
async def test_image_attachment_vision_question_routes_to_model(monkeypatch):
    assert await _drive(monkeypatch, "what do you see", attachments=[_IMG]) == ["model"]


@pytest.mark.anyio
async def test_data_file_attachment_with_file_request_still_makes_a_file(monkeypatch):
    # a non-image attachment (a CSV) plus "make a PDF report" is a legitimate file build
    assert await _drive(monkeypatch, "make a PDF report from this data", attachments=[_CSV]) == ["file"]


@pytest.mark.anyio
async def test_vague_followup_inherits_prior_file_intent(monkeypatch):
    # "make it blue" alone is vague → it inherits the previous turn's "create a PDF resume" → file
    history = [
        {"role": "user", "content": "create a PDF resume for me"},
        {"role": "assistant", "content": "Here is a draft."},
    ]
    assert await _drive(monkeypatch, "make it navy blue", history=history) == ["file"]


@pytest.mark.anyio
async def test_vague_followup_does_not_inherit_when_this_turn_has_an_attachment(monkeypatch):
    # same vague follow-up, but now the user attaches an image → the attachment is the subject,
    # the prior "create a PDF resume" is NOT inherited, and vision → chat only
    history = [
        {"role": "user", "content": "create a PDF resume for me"},
        {"role": "assistant", "content": "Here is a draft."},
    ]
    assert await _drive(monkeypatch, "make it navy blue", attachments=[_IMG], history=history) == ["model"]
