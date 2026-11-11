"""Safe arithmetic evaluator.

Models are unreliable at exact arithmetic, so we give them a calculator.
We parse with `ast` and only allow a whitelist of node types, because
`eval` on model-written text would let it run arbitrary Python.

Maths is done with Decimal at 50 significant digits rather than float:
floats keep only ~16 digits, so "big number + small fraction" silently
lost precision and the model started finishing sums in its head.
"""

import ast
import decimal
import operator
from decimal import Decimal

SPEC = {
    "name": "calculate",
    "description": (
        "Evaluate an arithmetic expression exactly (50 significant digits). Use this "
        "for ANY arithmetic, including tips, splits, percentages and unit prices; "
        "never do maths in your head. Put the WHOLE calculation in one expression "
        "rather than combining partial results yourself. Supports + - * / ** %, "
        "parentheses and round(x, ndigits). Write percentages as multiplication, "
        "e.g. 15% of 80 -> 80 * 0.15. Do not use it for unit conversions (use "
        "convert_units) or for dates/times."
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

PRECISION = 50
# Caps so expressions like 9**9**9 can't freeze the bot.
MAX_EXPONENT = 1000
MAX_EXPRESSION_LENGTH = 500


def _mod(a: Decimal, b: Decimal) -> Decimal:
    """Python-style modulo (result takes the sign of the divisor).

    Decimal's % follows the dividend's sign (-7 % 3 == -1), which would
    surprise anyone used to calculators or Python (-7 % 3 == 2).
    """
    result = a % b
    if result and (result < 0) != (b < 0):
        result += b
    return result


def _pow(base: Decimal, exponent: Decimal) -> Decimal:
    """Exact for whole-number exponents; float fallback for roots like 2 ** 0.5."""
    if abs(exponent) > MAX_EXPONENT:
        raise ValueError(f"exponent too large (max {MAX_EXPONENT})")
    if exponent == exponent.to_integral_value():
        return base ** int(exponent)
    if base < 0:
        raise ValueError("fractional power of a negative number")
    return Decimal(repr(float(base) ** float(exponent)))


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: _pow,
    ast.Mod: _mod,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval(node: ast.AST) -> Decimal:
    """Recursively evaluate a whitelisted AST node; anything else is rejected."""
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        # str() first so 0.1 becomes Decimal('0.1'), not 0.1000000000000000055...
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "round"
        and not node.keywords
        and 1 <= len(node.args) <= 2
    ):
        value = _eval(node.args[0])
        ndigits = int(_eval(node.args[1])) if len(node.args) == 2 else 0
        return round(value, ndigits)
    raise ValueError(f"unsupported syntax: {ast.dump(node)[:60]}")


def _to_json_number(value: Decimal) -> int | float | str:
    """Return the friendliest exact form: int, float if lossless, else a string.

    A float that can't represent the Decimal exactly would hand the model a
    rounded number again, so in that case we send all the digits as text.
    """
    if value == value.to_integral_value() and value.adjusted() < PRECISION:
        return int(value)
    as_float = float(value)
    if Decimal(repr(as_float)) == value:
        return as_float
    return format(value.normalize(), "f")


def calculate(expression: str) -> dict:
    """Evaluate `expression` and return {"expression", "result"} or {"error"}."""
    if len(expression) > MAX_EXPRESSION_LENGTH:
        return {"error": "expression too long"}
    try:
        with decimal.localcontext() as ctx:
            ctx.prec = PRECISION
            tree = ast.parse(expression, mode="eval")
            result = _eval(tree.body)
            # Convert inside the context: normalize() outside it would round
            # back down to Python's default 28 digits.
            output = _to_json_number(result)
    except ZeroDivisionError:  # decimal.DivisionByZero is a subclass
        return {"error": "division by zero"}
    except decimal.InvalidOperation:
        return {"error": "undefined result (e.g. 0/0)"}
    except (SyntaxError, ValueError, OverflowError) as exc:
        return {"error": f"could not evaluate: {exc}"}
    return {"expression": expression, "result": output}
