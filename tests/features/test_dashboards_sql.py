"""Dashboard widget SQL validation, including the Postgres-dialect fallback that keeps dashboards
working in a packaged build where sqlglot's dynamically-loaded dialect submodule was not bundled.
"""

import sqlglot

from backend.features import dashboards


def test_accepts_a_single_select():
    assert dashboards.validate_widget_sql("SELECT id, name FROM users") is None
    assert dashboards.validate_widget_sql("SELECT * FROM t WHERE a = 1 ORDER BY a") is None


def test_rejects_non_select_and_multi_statement():
    assert dashboards.validate_widget_sql("DELETE FROM users") is not None
    assert dashboards.validate_widget_sql("DROP TABLE users") is not None
    assert dashboards.validate_widget_sql("SELECT 1; SELECT 2") is not None
    assert dashboards.validate_widget_sql("SELECT 1; DELETE FROM users") is not None


def test_reports_genuine_parse_errors():
    err = dashboards.validate_widget_sql("SELECT * FROM WHERE ))")
    assert err and err.startswith("SQL didn't parse")


def test_falls_back_when_the_postgres_dialect_is_unavailable(monkeypatch):
    """A packaged build may lack sqlglot.dialects.postgres; validation must degrade to the default
    dialect instead of turning every widget into "No module named 'sqlglot.dialects.postgres'"."""
    real_parse = sqlglot.parse

    def parse_without_postgres(sql, read=None, **kwargs):
        if read == "postgres":
            raise ModuleNotFoundError("No module named 'sqlglot.dialects.postgres'")
        return real_parse(sql, read=None, **kwargs)

    monkeypatch.setattr(sqlglot, "parse", parse_without_postgres)

    # Still validates correctly with the default dialect — no dialect error leaks to the widget.
    assert dashboards.validate_widget_sql("SELECT id FROM users") is None
    assert dashboards.validate_widget_sql("DELETE FROM users") is not None
    assert "sqlglot.dialects" not in (dashboards.validate_widget_sql("SELECT 1") or "")
