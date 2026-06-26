"""Smoke test: core modules import without side effects that require a live database.

Importing backend.core.queue must NOT require a configured database — the queue app is
built lazily via get_queue_app(), so the setup flow can run before a DB is connected.
"""


def test_core_modules_import_without_side_effects():
    import backend.core.appconfig  # noqa: F401
    import backend.core.config  # noqa: F401
    import backend.core.database  # noqa: F401
    import backend.core.migrations  # noqa: F401
    import backend.core.models  # noqa: F401
    import backend.core.queue  # noqa: F401


def test_queue_app_is_lazy():
    from backend.core import queue
    assert callable(queue.get_queue_app)
    assert callable(queue.reset_queue_app)
