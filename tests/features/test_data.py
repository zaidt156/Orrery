import datetime
import uuid

from backend.features import data


def test_coerce_async_uses_psycopg_driver():
    u = data._coerce_async("postgresql://u:p@host:5432/db")
    assert u.drivername == "postgresql+psycopg"
    u2 = data._coerce_async("postgres://u:p@host/db")
    assert u2.drivername == "postgresql+psycopg"


def test_display_has_no_password():
    u = data._coerce_async("postgresql://user:SECRETPW@db.example.com:6543/sales")
    disp = data._display(u)
    assert "SECRETPW" not in disp
    assert disp == "db.example.com:6543/sales"


def test_quote_ident_escapes_quotes():
    # an injection attempt via a doubled quote is neutralized
    assert data._quote_ident('orders') == '"orders"'
    assert data._quote_ident('a"; DROP TABLE x;--') == '"a""; DROP TABLE x;--"'


def test_cell_stringifies_non_json_types():
    assert data._cell(None) is None
    assert data._cell(5) == 5
    assert data._cell(True) is True
    assert data._cell("x") == "x"
    assert isinstance(data._cell(uuid.uuid4()), str)
    assert isinstance(data._cell(datetime.datetime.now()), str)
