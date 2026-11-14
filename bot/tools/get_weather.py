"""Current weather and today's forecast from Open-Meteo (free, no API key)."""

import httpx

from bot import config

SPEC = {
    "name": "get_weather",
    "description": (
        "Get the current weather and today's forecast (high/low, chance of rain) "
        "for a city. Pass the user's city from their saved facts when you know it "
        "(e.g. 'Lives in Toronto' -> location='Toronto'); leave location out to use "
        "the configured home city. Use for any question about weather, what to "
        "wear, or whether to take an umbrella. Not for forecasts beyond today."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name, optionally with country, e.g. 'Paris, France'."}
        },
    },
}

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 10.0

# WMO weather interpretation codes -> plain English (Open-Meteo docs).
WEATHER_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}

# Tests swap this for a mock transport so no real network is used.
_transport: httpx.AsyncBaseTransport | None = None


def describe(code: int | None) -> str:
    return WEATHER_CODES.get(code, "unknown conditions") if code is not None else "unknown conditions"


async def _geocode(client: httpx.AsyncClient, location: str) -> dict | None:
    """City name -> best match with coordinates, or None if not found.

    'Paris, France' is split so the search gets 'Paris' (the API matches
    place names, not full addresses) and the country picks the right Paris.
    """
    name, _, hint = (part.strip() for part in location.partition(","))
    resp = await client.get(GEOCODE_URL, params={"name": name, "count": 5, "language": "en", "format": "json"})
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if hint:
        hinted = [r for r in results if hint.lower() in f"{r.get('country', '')} {r.get('admin1', '')}".lower()]
        results = hinted or results
    return results[0] if results else None


async def get_weather(location: str | None = None) -> dict:
    """Weather for `location`, falling back to HOME_CITY."""
    location = (location or "").strip() or config.HOME_CITY
    if not location:
        return {"error": "no location given and no HOME_CITY configured; ask the user which city"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=_transport) as client:
            place = await _geocode(client, location)
            if place is None:
                return {"error": f"couldn't find a place called {location!r}"}
            resp = await client.get(FORECAST_URL, params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "timezone": "auto",  # "today" in the place's own timezone
                "forecast_days": 1,
            })
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        return {"error": "the weather service timed out"}
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"error": f"weather lookup failed: {exc.__class__.__name__}"}

    current, daily = data["current"], data["daily"]
    rain = daily["precipitation_probability_max"][0]
    today = describe(daily["weather_code"][0])
    summary = (
        f"Now {describe(current['weather_code'])}, {round(current['temperature_2m'])}°C "
        f"(feels like {round(current['apparent_temperature'])}°C). "
        f"Today {today}, high {round(daily['temperature_2m_max'][0])}°C, "
        f"low {round(daily['temperature_2m_min'][0])}°C"
        + (f", {rain}% chance of rain." if rain is not None else ".")
    )
    return {
        "place": ", ".join(p for p in (place.get("name"), place.get("admin1"), place.get("country")) if p),
        "temperature_c": current["temperature_2m"],
        "feels_like_c": current["apparent_temperature"],
        "high_c": daily["temperature_2m_max"][0],
        "low_c": daily["temperature_2m_min"][0],
        "rain_chance_pct": rain,
        "wind_kmh": current["wind_speed_10m"],
        "conditions_now": describe(current["weather_code"]),
        "conditions_today": today,
        "summary": summary,
    }
