"""Tests for get_weather with a mock HTTP transport (no network)."""

import asyncio

import httpx
import pytest

from bot import config
from bot.tools import get_weather as mod

GEO = {"results": [
    {"name": "Paris", "admin1": "Texas", "country": "United States", "latitude": 33.66, "longitude": -95.55},
    {"name": "Paris", "admin1": "Île-de-France", "country": "France", "latitude": 48.85, "longitude": 2.35},
]}
FORECAST = {
    "current": {"temperature_2m": 5.1, "apparent_temperature": -0.4, "weather_code": 61, "wind_speed_10m": 21.4},
    "daily": {"temperature_2m_max": [6.6], "temperature_2m_min": [0.8],
              "precipitation_probability_max": [80], "weather_code": [63]},
}


def use(monkeypatch, handler):
    monkeypatch.setattr(mod, "_transport", httpx.MockTransport(handler))


def happy(requests):
    def handler(req):
        requests.append(req)
        if "geocoding" in req.url.host:
            return httpx.Response(200, json=GEO)
        return httpx.Response(200, json=FORECAST)
    return handler


def test_returns_conditions_and_summary(monkeypatch):
    requests = []
    use(monkeypatch, happy(requests))
    result = asyncio.run(mod.get_weather("Paris"))
    assert result["place"] == "Paris, Texas, United States"  # first match without a hint
    assert result["high_c"] == 6.6 and result["low_c"] == 0.8 and result["rain_chance_pct"] == 80
    assert result["conditions_now"] == "light rain" and result["conditions_today"] == "rain"
    assert result["summary"] == (
        "Now light rain, 5°C (feels like 0°C). Today rain, high 7°C, low 1°C, 80% chance of rain.")
    assert requests[1].url.params["timezone"] == "auto"


def test_country_hint_picks_the_right_city(monkeypatch):
    requests = []
    use(monkeypatch, happy(requests))
    result = asyncio.run(mod.get_weather("Paris, France"))
    assert result["place"] == "Paris, Île-de-France, France"
    assert requests[0].url.params["name"] == "Paris"
    assert requests[1].url.params["latitude"] == "48.85"


def test_falls_back_to_home_city(monkeypatch):
    requests = []
    use(monkeypatch, happy(requests))
    monkeypatch.setattr(config, "HOME_CITY", "Paris, France")
    assert asyncio.run(mod.get_weather())["place"].endswith("France")


def test_no_location_at_all(monkeypatch):
    monkeypatch.setattr(config, "HOME_CITY", "")
    assert "ask the user" in asyncio.run(mod.get_weather())["error"]


def test_unknown_city(monkeypatch):
    use(monkeypatch, lambda req: httpx.Response(200, json={"generationtime_ms": 0.1}))
    assert "couldn't find" in asyncio.run(mod.get_weather("Qwzxqwzx"))["error"]


def test_timeout_and_http_error(monkeypatch):
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)
    use(monkeypatch, slow)
    assert "timed out" in asyncio.run(mod.get_weather("Paris"))["error"]
    use(monkeypatch, lambda req: httpx.Response(503))
    assert "failed" in asyncio.run(mod.get_weather("Paris"))["error"]


@pytest.mark.parametrize("code,text", [(0, "clear sky"), (95, "thunderstorm"), (1234, "unknown conditions"),
                                       (None, "unknown conditions")])
def test_weather_codes(code, text):
    assert mod.describe(code) == text
