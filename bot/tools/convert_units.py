"""Unit conversion: length, weight, temperature and cooking volume.

Each linear unit is stored as a factor to a base unit (metre, gram,
millilitre). Temperature is not linear, so it has its own formulas. Cups to
grams depends on the ingredient, so we use an approximate density table.
"""

SPEC = {
    "name": "convert_units",
    "description": (
        "Convert a quantity between units of length, weight, temperature or "
        "cooking volume (cups, tbsp, tsp, ml, l, fl_oz). Can also convert between "
        "volume and weight for common ingredients (e.g. cups of flour to grams). "
        "Use this instead of recalling conversion factors from memory. "
        "Do not use it for currency or time zones, and use calculate for plain "
        "arithmetic on numbers that are already in the right unit."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "value": {"type": "number", "description": "The amount to convert."},
            "from_unit": {"type": "string", "description": "Unit to convert from, e.g. 'mi', 'lb', 'F', 'cup'."},
            "to_unit": {"type": "string", "description": "Unit to convert to, e.g. 'km', 'kg', 'C', 'g'."},
            "ingredient": {
                "type": "string",
                "description": (
                    "Only for volume<->weight conversions: water, milk, flour, "
                    "sugar, brown_sugar, butter, rice, oil, honey. Defaults to water."
                ),
            },
        },
        "required": ["value", "from_unit", "to_unit"],
    },
}

# factor to base unit
LENGTH = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
          "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344}
WEIGHT = {"mg": 0.001, "g": 1.0, "kg": 1000.0, "oz": 28.349523125, "lb": 453.59237}
VOLUME = {"ml": 1.0, "l": 1000.0, "tsp": 4.92892, "tbsp": 14.7868,
          "fl_oz": 29.5735, "cup": 236.588, "pint": 473.176, "quart": 946.353,
          "gallon": 3785.41}
TEMPERATURE = {"c", "f", "k"}

# grams per millilitre (approximate, for cooking)
DENSITY = {"water": 1.0, "milk": 1.03, "flour": 0.53, "sugar": 0.85,
           "brown_sugar": 0.93, "butter": 0.96, "rice": 0.85, "oil": 0.92,
           "honey": 1.42}

ALIASES = {
    "millimeter": "mm", "millimetre": "mm", "centimeter": "cm", "centimetre": "cm",
    "meter": "m", "metre": "m", "kilometer": "km", "kilometre": "km",
    "inch": "in", "inches": "in", "foot": "ft", "feet": "ft", "yard": "yd",
    "mile": "mi", "miles": "mi", "gram": "g", "grams": "g", "kilogram": "kg",
    "kilo": "kg", "kilos": "kg", "ounce": "oz", "ounces": "oz", "pound": "lb",
    "pounds": "lb", "lbs": "lb", "milliliter": "ml", "millilitre": "ml",
    "liter": "l", "litre": "l", "teaspoon": "tsp", "tablespoon": "tbsp",
    "cups": "cup", "fluid_ounce": "fl_oz", "floz": "fl_oz",
    "celsius": "c", "fahrenheit": "f", "kelvin": "k",
    "°c": "c", "°f": "f",
}


def _normalise(unit: str) -> str:
    """Lower-case, strip a trailing 's' plural, and map aliases to short codes."""
    u = unit.strip().lower().replace(" ", "_")
    u = ALIASES.get(u, u)
    if u not in LENGTH | WEIGHT | VOLUME and u not in TEMPERATURE and u.endswith("s"):
        u = ALIASES.get(u[:-1], u[:-1])
    return u


def _convert_temperature(value: float, f: str, t: str) -> float:
    """Go via Celsius: easier to read than a 3x3 table of formulas."""
    celsius = {"c": value, "f": (value - 32) * 5 / 9, "k": value - 273.15}[f]
    return {"c": celsius, "f": celsius * 9 / 5 + 32, "k": celsius + 273.15}[t]


def convert_units(value: float, from_unit: str, to_unit: str, ingredient: str = "water") -> dict:
    """Convert `value` and return {"value", "unit", ...} or {"error"}."""
    f, t = _normalise(from_unit), _normalise(to_unit)
    result: float | None = None
    note = None

    if f in TEMPERATURE and t in TEMPERATURE:
        result = _convert_temperature(value, f, t)
    else:
        for table in (LENGTH, WEIGHT, VOLUME):
            if f in table and t in table:
                result = value * table[f] / table[t]
                break
        else:
            # Cooking: volume <-> weight via density.
            density = DENSITY.get(ingredient.strip().lower().replace(" ", "_"))
            if (f in VOLUME and t in WEIGHT) or (f in WEIGHT and t in VOLUME):
                if density is None:
                    return {"error": f"unknown ingredient {ingredient!r}; known: {', '.join(DENSITY)}"}
                if f in VOLUME:
                    grams = value * VOLUME[f] * density
                    result = grams / WEIGHT[t]
                else:
                    ml = value * WEIGHT[f] / density
                    result = ml / VOLUME[t]
                note = f"approximate, assumes {ingredient}"

    if result is None:
        return {"error": f"cannot convert {from_unit!r} to {to_unit!r}"}
    out = {"value": round(result, 4), "unit": to_unit, "from": f"{value} {from_unit}"}
    if note:
        out["note"] = note
    return out
