"""Safe arithmetic evaluator.

Models are unreliable at exact arithmetic, so we give them a calculator.
We parse with `ast` and only allow a whitelist of node types, because
`eval` on model-written text would let it run arbitrary Python.
"""

import ast
import operator

SPEC = {
    "name": "calculate",
    "description": (
        "Evaluate an arithmetic expression exactly. Use this for ANY arithmetic, "
        "including tips, splits, percentages and unit prices; never do maths in "
        "your head. Supports + - * / ** %, parentheses and round(x, ndigits). "
        "Write percentages as multiplication, e.g. 15% of 80 -> 80 * 0.15. "
        "Do not use it for unit conversions (use convert_units) or for dates/times."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Arithmetic expression, e.g. 'round((84.50 * 1.18) / 3, 2)'",
            }
        },
        "required": ["expression"],
    },
}

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

# Caps so expressions like 9**9**9 can't freeze the bot.
MAX_EXPONENT = 1000
MAX_EXPRESSION_LENGTH = 500


def _eval(node: ast.AST) -> float | int:
    """Recursively evaluate a whitelisted AST node; anything else is rejected."""
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError(f"exponent too large (max {MAX_EXPONENT})")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "round"
        and not node.keywords
        and 1 <= len(node.args) <= 2
    ):
        args = [_eval(a) for a in node.args]
        if len(args) == 2:
            args[1] = int(args[1])
        return round(*args)
    raise ValueError(f"unsupported syntax: {ast.dump(node)[:60]}")


def calculate(expression: str) -> dict:
    """Evaluate `expression` and return {"expression", "result"} or {"error"}."""
    if len(expression) > MAX_EXPRESSION_LENGTH:
        return {"error": "expression too long"}
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree.body)
    except ZeroDivisionError:
        return {"error": "division by zero"}
    except (SyntaxError, ValueError, OverflowError) as exc:
        return {"error": f"could not evaluate: {exc}"}
    if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
        result = int(result)
    return {"expression": expression, "result": result}
