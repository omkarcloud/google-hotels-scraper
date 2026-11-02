"""Live endpoint smoke tests: one call per /google-hotels/* route against a
running service, with example values proven to return data (2026-11-02,
Bellagio Las Vegas). The listing tooling reads each route's FIRST call from
this file's AST as its working example, so the values stay literals.

Skipped unless GOOGLE_HOTELS_BASE points at a running service:

    ONLY_SCRAPER=google-hotels SCRAPERS_PORT=6031 python run.py --dev
    GOOGLE_HOTELS_BASE=http://127.0.0.1:6031 python -m pytest google_hotels/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("GOOGLE_HOTELS_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set GOOGLE_HOTELS_BASE to run live endpoint tests")

BELLAGIO = "ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE"


def call(path, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=240)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def status(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=240).status_code


def test_hotel_details():
    body = call("/google-hotels/hotels/details", hotel="ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE")
    assert body["name"].startswith("Bellagio")
    assert body["hotel_class"] == 5
    assert body["location"]["address"]
    assert body["amenity_groups"]
    assert status("/google-hotels/hotels/details", hotel="ChkIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA") == 404


def test_hotel_prices():
    body = call("/google-hotels/hotels/prices", hotel="ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE")
    assert body["offers"] and body["offers"][0]["vendor"]
    assert body["price"]["nightly"]["amount"] > 0


def test_hotels_search():
    body = call("/google-hotels/hotels/search", query="hotels in Las Vegas")
    assert len(body["results"]) == 20
    assert body["next"]
    assert status("/google-hotels/hotels/search", query="hotels in Las Vegas", sort="cheapest") == 400


def test_hotel_reviews():
    body = call("/google-hotels/hotels/reviews", hotel="ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE")
    assert body["reviews"] and body["next_token"]


def test_hotel_photos():
    body = call("/google-hotels/hotels/photos", hotel="ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE")
    assert body["photos"] and body["categories"]


def test_places_autocomplete():
    body = call("/google-hotels/places/autocomplete", query="hotels in las v")
    assert body["suggestions"]


def test_places_price_trends():
    body = call("/google-hotels/places/price-trends", query="Las Vegas")
    assert len(body["months"]) == 12
