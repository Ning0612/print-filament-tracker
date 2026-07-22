"""Unit tests for the ledger number formatting Jinja filters (web/app.py)."""

import pytest

from web.app import fmt_duration, fmt_int, fmt_money, fmt_weight, ledger_amount


class TestFmtInt:
    def test_thousands(self):
        assert fmt_int(1234567) == "1,234,567"

    def test_rounds_float(self):
        assert fmt_int(1999.6) == "2,000"

    def test_zero(self):
        assert fmt_int(0) == "0"

    def test_none(self):
        assert fmt_int(None) == "-"

    def test_invalid_string(self):
        assert fmt_int("abc") == "-"


class TestFmtWeight:
    def test_default_unit(self):
        assert fmt_weight(3200) == "3,200.0 g"

    def test_kg_unit_and_digits(self):
        assert fmt_weight(3.2, unit="kg", digits=2) == "3.20 kg"

    def test_negative(self):
        assert fmt_weight(-12.34) == "-12.3 g"

    def test_none(self):
        assert fmt_weight(None) == "-"

    def test_numeric_string(self):
        assert fmt_weight("15.5") == "15.5 g"


class TestFmtMoney:
    def test_default_lang_suffix(self, app_ctx):
        # default lang zh: "{amount} 元"
        assert fmt_money(1234.5) == "1,234.50 元"

    def test_none(self, app_ctx):
        assert fmt_money(None) == "-"

    def test_zero(self, app_ctx):
        assert fmt_money(0) == "0.00 元"


class TestFmtDuration:
    def test_hours_and_minutes(self):
        assert fmt_duration(3 * 3600 + 12 * 60) == "3 h 12 m"

    def test_minutes_only(self):
        assert fmt_duration(59 * 60) == "59 m"

    def test_zero(self):
        assert fmt_duration(0) == "0 m"

    def test_none(self):
        assert fmt_duration(None) == "-"


class TestLedgerAmount:
    def test_debit_class(self):
        html = str(ledger_amount("12.3 g", "debit"))
        assert html == '<span class="amount amount--debit">12.3 g</span>'

    def test_credit_class(self):
        html = str(ledger_amount("1.0 kg", "credit"))
        assert 'class="amount amount--credit"' in html

    def test_neutral_default(self):
        html = str(ledger_amount("5 m"))
        assert 'class="amount"' in html

    def test_escapes_html(self):
        html = str(ledger_amount("<script>"))
        assert "<script>" not in html


@pytest.fixture
def app_ctx(db_path):
    """App + request context so fmt_money can resolve the session locale."""
    from web.app import create_app

    app = create_app(db_path=db_path)
    with app.test_request_context("/"):
        yield app
