import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.db.verify_sql import verify_sql, UnsafeSQLError, MultipleStatementsError


def test_verify_sql_appends_limit():
    sql = "SELECT * FROM users"
    safe_sql = verify_sql(sql, cost_guard=False)
    assert safe_sql.strip().endswith("LIMIT 1000")


def test_verify_sql_rejects_mutating():
    with pytest.raises(UnsafeSQLError):
        verify_sql("DELETE FROM users", cost_guard=False)


def test_verify_sql_rejects_multiple_statements():
    with pytest.raises(MultipleStatementsError):
        verify_sql("SELECT 1; DROP TABLE users", cost_guard=False)
