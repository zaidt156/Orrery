"""First-run Docker bootstrap decisions (pure logic — no Docker calls)."""
from backend.core import dockerboot


def test_autoprovision_only_when_unconfigured_and_headless():
    # installed desktop app: no URL, no console → provision automatically
    assert dockerboot.should_autoprovision(None, stdin_isatty=False) is True
    # a console is attached (portable script / dev run) → the interactive prompt handles it
    assert dockerboot.should_autoprovision(None, stdin_isatty=True) is False
    # already configured → never touch Docker
    assert dockerboot.should_autoprovision("postgresql+psycopg://u:p@h/db", stdin_isatty=False) is False


def test_should_ensure_local_covers_fresh_and_returning_bundled_users():
    LOCAL = "postgresql+psycopg://orrery:orrery_dev_password@127.0.0.1:5432/orrery"
    EXTERNAL = "postgresql+psycopg://me:pw@db.example.com:5432/prod"
    # fresh install, headless → bring the bundled DB up (starting Docker if needed)
    assert dockerboot.should_ensure_local(None, stdin_isatty=False) is True
    # returning user whose SAVED url IS the bundled local DB → still ensure it (the reported bug:
    # reopening with Docker stopped used to skip this and just fail)
    assert dockerboot.should_ensure_local(LOCAL, stdin_isatty=False) is True
    assert dockerboot.should_ensure_local(LOCAL.replace("127.0.0.1", "localhost"), stdin_isatty=False) is True
    # a user's own EXTERNAL Postgres → never auto-manage Docker for it
    assert dockerboot.should_ensure_local(EXTERNAL, stdin_isatty=False) is False
    # a console (dev / setup script) manages Docker itself
    assert dockerboot.should_ensure_local(None, stdin_isatty=True) is False
    assert dockerboot.should_ensure_local(LOCAL, stdin_isatty=True) is False


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
