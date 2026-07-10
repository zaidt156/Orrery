"""First-run Docker bootstrap decisions (pure logic — no Docker calls)."""
from backend.core import dockerboot


def test_autoprovision_only_when_unconfigured_and_headless():
    # installed desktop app: no URL, no console → provision automatically
    assert dockerboot.should_autoprovision(None, stdin_isatty=False) is True
    # a console is attached (portable script / dev run) → the interactive prompt handles it
    assert dockerboot.should_autoprovision(None, stdin_isatty=True) is False
    # already configured → never touch Docker
    assert dockerboot.should_autoprovision("postgresql+psycopg://u:p@h/db", stdin_isatty=False) is False


def test_run_args_match_the_bundled_compose_service():
    args = dockerboot.run_args()
    joined = " ".join(args)
    assert args[:3] == ["docker", "run", "-d"]
    assert "--name orrery-postgres" in joined
    assert "pgvector/pgvector:pg17" in joined
    # localhost-only publish — the bundled database must never listen on the network
    assert "127.0.0.1:5432:5432" in joined
    assert "orrery_pgdata:/var/lib/postgresql/data" in joined


def test_default_url_targets_the_bundled_container():
    assert dockerboot.DEFAULT_URL.startswith("postgresql+psycopg://orrery:")
    assert "127.0.0.1:5432/orrery" in dockerboot.DEFAULT_URL


def test_setup_markers_are_stable_strings():
    # the Electron shell greps the backend log for these exact markers to show the right dialog
    assert dockerboot.MARKER_DOCKER_MISSING == "ORRERY_SETUP:DOCKER_MISSING"
    assert dockerboot.MARKER_DOCKER_STOPPED == "ORRERY_SETUP:DOCKER_STOPPED"
    assert dockerboot.MARKER_PROVISION_FAILED == "ORRERY_SETUP:PROVISION_FAILED"
