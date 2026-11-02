"""Offline tests for the /google-hotels/* request schemas.

    python -m pytest google_hotels/test_schemas.py -q
"""
import os
import sys
from datetime import date, timedelta

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_hotels import refs, schemas  # noqa: E402

TOKEN = "ChkInMKgie3-lY1lGg0vZy8xMXJ0X3M0dno0EAE"
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
IN_A_WEEK = (date.today() + timedelta(days=7)).isoformat()
IN_TEN_DAYS = (date.today() + timedelta(days=10)).isoformat()


def test_search_defaults():
    loaded = schemas.HotelsSearchSchema().load({"query": " hotels in paris "})
    assert loaded["query"] == "hotels in paris"
    assert loaded["check_in"] == TOMORROW
    assert loaded["check_out"] == (date.today() + timedelta(days=2)).isoformat()
    assert loaded["adults"] == 2 and loaded["children_ages"] is None
    assert loaded["currency"] == "USD" and loaded["language"] == "en" and loaded["country"] == "US"
    assert loaded["sort"] == "relevance" and loaded["page"] == 1
    assert loaded["property_type"] == 1
    assert loaded["min_price"] is None and loaded["hotel_class"] is None and loaded["amenities"] is None


def test_search_full():
    loaded = schemas.HotelsSearchSchema().load({
        "query": "lisbon", "check_in": IN_A_WEEK, "check_out": IN_TEN_DAYS, "adults": "3", "children_ages": "5, 12",
        "currency": "eur", "language": "fr", "country": "fr", "sort": "Lowest_Price", "min_price": "50",
        "max_price": "300", "hotel_class": "4,5", "min_rating": "4", "amenities": "pool, Free_Wifi",
        "property_type": "vacation_rental", "page": "3"})
    assert loaded["children_ages"] == [5, 12]
    assert loaded["currency"] == "EUR" and loaded["country"] == "FR" and loaded["language"] == "fr"
    assert loaded["sort"] == "lowest_price"
    assert loaded["hotel_class"] == ["4", "5"]
    assert loaded["min_rating"] == 8
    assert loaded["amenities"] == [6, 35]
    assert loaded["property_type"] == 2
    assert loaded["page"] == 3


@pytest.mark.parametrize("params,field", [
    ({}, "query"),
    ({"query": "x", "check_in": "2020-01-01"}, "check_in"),
    ({"query": "x", "check_in": IN_A_WEEK, "check_out": IN_A_WEEK}, "check_out"),
    ({"query": "x", "check_in": TOMORROW, "check_out": (date.today() + timedelta(days=40)).isoformat()}, "check_out"),
    ({"query": "x", "adults": "9"}, "adults"),
    ({"query": "x", "children_ages": "19"}, "children_ages"),
    ({"query": "x", "sort": "cheapest"}, "sort"),
    ({"query": "x", "hotel_class": "1"}, "hotel_class"),
    ({"query": "x", "min_rating": "3"}, "min_rating"),
    ({"query": "x", "amenities": "sauna"}, "amenities"),
    ({"query": "x", "min_price": "300", "max_price": "100"}, "max_price"),
    ({"query": "x", "page": "0"}, "page"),
    ({"query": "x", "page": str(refs.MAX_PAGE + 1)}, "page"),
    ({"query": "x", "currency": "dollars"}, "currency"),
    ({"query": "x", "country": "usa"}, "country"),
    ({"query": "x", "url": "https://www.google.com"}, "url"),
])
def test_search_rejects(params, field):
    with pytest.raises(ValidationError) as err:
        schemas.HotelsSearchSchema().load(params)
    assert field in err.value.messages


def test_hotel_schema_accepts_token_and_link():
    assert schemas.HotelSchema().load({"hotel": TOKEN})["hotel"] == TOKEN
    loaded = schemas.HotelSchema().load({"hotel": f"https://www.google.com/travel/hotels/entity/{TOKEN}/prices?hl=en"})
    assert loaded["hotel"] == TOKEN
    assert loaded["check_in"] == TOMORROW and loaded["adults"] == 2


@pytest.mark.parametrize("value", ["", "the people paris", "https://booking.com/hotel/x", "ChkI"])
def test_hotel_schema_rejects(value):
    with pytest.raises(ValidationError) as err:
        schemas.HotelSchema().load({"hotel": value})
    assert "hotel" in err.value.messages


def test_hotel_schema_rejects_sibling_params():
    with pytest.raises(ValidationError):
        schemas.HotelSchema().load({"hotel": TOKEN, "id": TOKEN})


def test_reviews_schema():
    loaded = schemas.ReviewsSchema().load({"hotel": TOKEN})
    assert loaded == {"hotel": TOKEN, "sort": 1, "limit": 10, "next_token": None, "language": "en", "country": "US"}
    loaded = schemas.ReviewsSchema().load({"hotel": TOKEN, "sort": "Most_Recent", "limit": "50", "next_token": "CjEIARIp:10"})
    assert loaded["sort"] == 2 and loaded["limit"] == 50 and loaded["next_token"] == "CjEIARIp:10"
    with pytest.raises(ValidationError) as err:
        schemas.ReviewsSchema().load({"hotel": TOKEN, "limit": "51"})
    assert "limit" in err.value.messages
    with pytest.raises(ValidationError) as err:
        schemas.ReviewsSchema().load({"hotel": TOKEN, "sort": "newest"})
    assert "sort" in err.value.messages


def test_photos_schema():
    assert schemas.PhotosSchema().load({"hotel": TOKEN}) == {"hotel": TOKEN, "language": "en", "country": "US"}
    with pytest.raises(ValidationError):
        schemas.PhotosSchema().load({"hotel": TOKEN, "page": "2"})


def test_autocomplete_schema():
    assert schemas.AutocompleteSchema().load({"query": "hotels in lis"}) == {
        "query": "hotels in lis", "language": "en", "country": "US"}
    with pytest.raises(ValidationError) as err:
        schemas.AutocompleteSchema().load({"query": "x" * 101})
    assert "query" in err.value.messages


def test_price_trends_schema():
    loaded = schemas.PriceTrendsSchema().load({"query": "Bali", "currency": "idr"})
    assert loaded == {"query": "Bali", "currency": "IDR", "language": "en", "country": "US"}
    with pytest.raises(ValidationError):
        schemas.PriceTrendsSchema().load({})
