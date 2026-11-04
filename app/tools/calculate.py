import ast
import operator
from decimal import Decimal, InvalidOperation

from app.calculators.rules import to_money

MAX_EXPRESSION_LENGTH = 200

BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _evaluate(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY_OPERATORS:
        return BINARY_OPERATORS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY_OPERATORS:
        return UNARY_OPERATORS[type(node.op)](_evaluate(node.operand))
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


def calculate(expression: str) -> Decimal:
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"expression longer than {MAX_EXPRESSION_LENGTH} characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as error:
        raise ValueError("invalid expression") from error
    try:
        return to_money(_evaluate(tree))
    except (ZeroDivisionError, InvalidOperation) as error:
        raise ValueError("division by zero") from error
