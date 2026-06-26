"""Core database URL normalization — the live engine path and the test path must agree."""

from backend.core.database import normalize_url


def test_normalize_postgres_url():
    assert normalize_url("postgres://u:p@h:5432/db").startswith("postgresql+psycopg://")
    assert normalize_url("postgresql://u:p@h:5432/db").startswith("postgresql+psycopg://")
    assert normalize_url("postgresql+psycopg://u:p@h:5432/db").startswith("postgresql+psycopg://")


def test_normalize_url_preserves_body():
    assert normalize_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"


def test_normalize_url_blank():
    assert normalize_url("") == ""
    assert normalize_url("   ") == ""
