"""Smoke test: every feature module must import cleanly.

This is the cheapest possible guard against the class of bug where a bad merge or
syntax error in one feature module breaks the whole backend at startup (chat.py
imports most of these at module load).
"""


def test_feature_modules_import():
    import backend.features.artifacts  # noqa: F401
    import backend.features.chat  # noqa: F401
    import backend.features.code_images  # noqa: F401
    import backend.features.data  # noqa: F401
    import backend.features.docgen  # noqa: F401
    import backend.features.exports  # noqa: F401
    import backend.features.feedback  # noqa: F401
    import backend.features.filegen  # noqa: F401
    import backend.features.filepreview  # noqa: F401
    import backend.features.files  # noqa: F401
    import backend.features.local_models  # noqa: F401
    import backend.features.rag  # noqa: F401
    import backend.features.sandbox  # noqa: F401
    import backend.features.skills  # noqa: F401
    import backend.features.taskrouter  # noqa: F401
    import backend.features.usage  # noqa: F401
