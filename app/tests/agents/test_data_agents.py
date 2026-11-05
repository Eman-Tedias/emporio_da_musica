from decimal import Decimal

from app.agents.data_agent import TOOL_SPECS, TOOLS, execute_tool


def test_every_spec_has_an_implementation():
    assert {spec["name"] for spec in TOOL_SPECS} == set(TOOLS)

def test_unknown_tool_is_refused():
    assert "error" in execute_tool("drop_table", {}, [])

def test_unexpected_arguments_are_refused():
    log = []
    result = execute_tool("calculate", {"expression": "1 + 1", "sql": "DELETE FROM orders"}, log)
    assert "error" in result

def test_calculate_runs_and_is_logged():
    log = []
    result = execute_tool("calculate", {"expression": "599.90 + 349.90"}, log)
    assert result["result"] == Decimal("949.80")
    assert log[0]["tool"] == "calculate"

def test_unsafe_expression_returns_an_error_instead_of_raising():
    assert "error" in execute_tool("calculate", {"expression": "__import__('os')"}, [])

def test_installments_validate_their_arguments():
    assert "error" in execute_tool("simulate_installments", {"total": 100, "installments": 99}, [])
    assert execute_tool("simulate_installments", {"total": 1200, "installments": 12}, [])["allowed"]