"""Money helpers: store whole cents, show with the currency symbol.

Floats can't represent most decimal amounts exactly (0.1 + 0.2 != 0.3), so
sums of float prices drift. Integer cents add up exactly.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from bot import config

MAX_CENTS = 1_000_000_000  # $10M: anything bigger is almost certainly a typo


def to_cents(amount: float | int | str) -> int:
    """12.5 -> 1250. Raises ValueError for non-numbers, <= 0 or absurd values."""
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {amount!r}") from exc
    cents = int(value * 100)
    if cents <= 0:
        raise ValueError("amount must be more than zero")
    if cents > MAX_CENTS:
        raise ValueError("amount is too large")
    return cents


def format_money(cents: int) -> str:
    """1250 -> '$12.50', 123456 -> '$1,234.56'."""
    return f"{config.CURRENCY}{cents // 100:,}.{cents % 100:02d}"
