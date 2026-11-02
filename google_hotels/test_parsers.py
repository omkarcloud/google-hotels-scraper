"""Offline tests for the Google Hotels parsers, reference resolvers and
protobuf helpers.

    python -m pytest google_hotels/test_parsers.py -q

Fixtures (google_hotels/fixtures/, captured 2026-10-30/31 from
www.google.com, no network):
  search_rpc_paris_page1                 AtySUc "hotels in paris", 2 adults, USD, 20 records
                                         (hotels, hostels and 2 vacation rentals)
  search_rpc_hotel_name_the_people_belleville   AtySUc for a hotel NAME: one matched hotel
  entity_prices_ds1_the_people_paris_marais     ds:1 of /travel/hotels/entity/<token>/prices (INR)
  entity_page_amenities_the_people_paris_marais.html   the amenities dialog + popular strip
  entity_page_not_found.html             the empty-title shell an unknown token gets
  reviews_rpc_the_people_paris_marais    ocp93e, 10 reviews + continuation token
  photos_rpc_the_people_paris_marais     pSDzMb gallery; photo_categories_rpc_* = zM1L7d
  autocomplete_rpc_hotels_in_lisb        mejVKc
  price_trends_rpc_paris                 axSywf
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_hotels import parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    path = os.path.join(FX, name)
    if name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def search():
    return P.parse_search(fixture("search_rpc_paris_page1.json.gz"), "USD")


@pytest.fixture(scope="module")
def entity():
    return P.parse_entity(fixture("entity_prices_ds1_the_people_paris_marais.json.gz"),
                          fixture("entity_page_amenities_the_people_paris_marais.html"), "INR")


# ---- refs ---------------------------------------------------------------------------

TOKEN = "ChkInMKgie3-lY1lGg0vZy8xMXJ0X3M0dno0EAE"


@pytest.mark.parametrize("value", [
    TOKEN,
    f"https://www.google.com/travel/hotels/entity/{TOKEN}",
    f"https://www.google.com/travel/hotels/entity/{TOKEN}/prices?q=hotels+in+paris&hl=en",
    f"https://www.google.fr/travel/hotels/the-people/entity/{TOKEN}?hl=fr",
    f"//www.google.co.uk/travel/hotels/entity/{TOKEN}/reviews",
])
def test_resolve_hotel_accepts_token_and_links(value):
    assert refs.resolve_hotel(value) == TOKEN


@pytest.mark.parametrize("value", ["", "paris", "https://example.com/travel/hotels/entity/" + TOKEN,
                                   "https://www.google.com/travel/flights", "12345"])
def test_resolve_hotel_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_hotel(value)


def test_children_ages_ref():
    assert refs.children_ages_ref("5, 12") == [5, 12]
    assert refs.children_ages_ref(" ") is None
    with pytest.raises(ValueError):
        refs.children_ages_ref("5,18")
    with pytest.raises(ValueError):
        refs.children_ages_ref("a")


@pytest.mark.parametrize("query,expected", [
    ("hotels in paris", "vacation rentals in paris"),
    ("Hotels near Times Square", "vacation rentals in Times Square"),
    ("Lisbon", "vacation rentals in Lisbon"),
    ("near Times Square", "vacation rentals in Times Square"),
    ("in Paris", "vacation rentals in Paris"),
    ("hotels in the Warehouse District", "vacation rentals in the Warehouse District"),
    ("Inn at the Lighthouse", "vacation rentals in Inn at the Lighthouse"),
    ("apartments in rome", "apartments in rome"),
    ("vacation rentals in bali", "vacation rentals in bali"),
])
def test_rentals_query(query, expected):
    assert refs.rentals_query(query) == expected


def test_cursor_and_qs():
    assert refs.search_cursor(1) is None
    assert refs.search_cursor(2) == "CBQ="          # proto{1: 20}
    assert refs.qs_param(1) is None
    assert refs.qs_param(2).startswith("EgRDQlE9")   # proto{2: "CBQ=", 7: 13}


def test_ts_param_matches_the_browser():
    """The exact `ts` the web client built for 2 adults, Dec 1-3 2026, USD."""
    assert refs.ts_param("2026-12-01", "2026-12-03", adults=2, currency="USD") == \
        "CAESCgoCCAMKAggDEAAaHBIaEhQKBwjqDxAMGAESBwjqDxAMGAMYATICEAAqCwoJOgNVU0RiAggB"
    with_child = refs.ts_param("2026-12-01", "2026-12-03", adults=2, children_ages=[12], currency="USD")
    assert with_child.startswith("CAESEAoCCAMKAggDCgQIAhAMEAEa")   # [3],[3],[2,12], 1 child


def test_ts_param_filters_and_rentals():
    hotels = refs.ts_param("2026-12-01", "2026-12-03")
    rentals = refs.ts_param("2026-12-01", "2026-12-03", kind=2, place={"id": "0x1:0x2", "name": "Paris"})
    assert hotels.startswith("CAES") and rentals.startswith("CAIS")
    filtered = refs.ts_param("2026-12-01", "2026-12-03", sort=3, hotel_classes=[4, 5], amenities=[6],
                             max_price=200, guest_rating=8)
    assert filtered != hotels and len(filtered) > len(hotels)


# ---- hotels/search ---------------------------------------------------------------------

def test_search_page(search):
    assert len(search["results"]) == 20
    assert search["total_count"] == 15000
    assert search["has_next"] is True
    assert search["is_single_hotel"] is False
    assert search["place"] == {"id": "0x47e66e1f06e2b70f:0x40b82c3688c9460", "name": "Paris"}


def test_search_record_fields(search):
    hotel = search["results"][0]
    assert hotel["id"] == "ChoIh--v1tzql_y2ARoNL2cvMTFjbHdtaGZ5bBAB"
    assert hotel["link"] == refs.hotel_link(hotel["id"])
    assert hotel["name"] == "The People Belleville"
    assert hotel["property_type"] == "hotel"
    assert hotel["primary_type"] == "hostel"
    assert hotel["rating"] == 4.3 and hotel["reviews_count"] == 2341
    assert hotel["price"]["nightly"] == {"amount": 60.92, "currency": "USD", "display": "$61"}
    assert hotel["price"]["total"]["display"] == "$122"
    assert hotel["price"]["taxes"] == 11.06 and hotel["price"]["fees"] == 0
    assert hotel["price"]["total_with_taxes_and_fees"] == 121.85
    assert hotel["price"]["deal"] == "29% less than usual"
    assert hotel["price"]["check_in"] == "2026-12-01" and hotel["price"]["check_out"] == "2026-12-03"
    assert hotel["location"]["latitude"] == pytest.approx(48.87, abs=0.01)
    assert hotel["location"]["country_code"] == "FR"
    assert hotel["contact"]["website"].startswith("https://www.thepeoplehostel.com/")
    assert hotel["check_in_time"] == "3:00 PM" and hotel["check_out_time"] == "12:00 PM"
    assert hotel["is_eco_certified"] is True
    assert hotel["ids"]["maps_cid"] == "5052524434146458705"
    assert hotel["ids"]["maps_feature_id"].startswith("0x")
    assert len(hotel["images"]) == 9 and hotel["images"][0]["original_link"].endswith("=s0")
    assert hotel["nearby"][1]["kind"] == "airport" and hotel["nearby"][1]["travel_times"][0]["duration"] == "34 min"
    assert hotel["reviews"]["histogram"][0] == {"stars": 5, "percent": 62, "count": 1410}
    assert any(t["name"] == "Sleep" and t["mentions"] == 205 for t in hotel["reviews"]["topics"])
    amenities = {a["id"]: a for a in hotel["amenities"]}
    assert amenities[29] == {"id": 29, "name": "Free Wi-Fi", "is_available": True}
    assert amenities[15]["is_available"] is False


def test_search_hotel_class_and_rentals(search):
    classed = {h["name"]: h["hotel_class"] for h in search["results"] if h["hotel_class"]}
    assert classed["Novotel Paris Est"] == 4
    assert classed["SO/ PARIS"] == 5
    rentals = [h for h in search["results"] if h["property_type"] == "vacation_rental"]
    assert len(rentals) == 2
    rental = rentals[0]["vacation_rental"]
    assert rental["bedrooms"] == 2 and rental["bathrooms"] == 1
    assert rental["check_in_time"] == "13:00" and rental["check_out_time"] == "11:00"
    assert rental["booking_sites"][0]["name"] == "Booking.com"
    assert rental["booking_sites"][0]["link"].startswith("https://www.booking.com/")
    assert search["results"][0]["vacation_rental"] is None


def test_search_hotel_name_answers_one_hotel():
    parsed = P.parse_search(fixture("search_rpc_hotel_name_the_people_belleville.json.gz"), "USD")
    assert parsed["is_single_hotel"] is True
    assert parsed["total_count"] == 1 and parsed["has_next"] is False
    hotel = parsed["results"][0]
    assert hotel["name"] == "The People Belleville"
    assert hotel["location"]["address"] == "59 Bd de Belleville, 75011 Paris, France"
    assert hotel["contact"]["phone"] == "+33 1 43 55 09 97"
    assert len(hotel["offers"]) == 11
    assert all(o["vendor"] for o in hotel["offers"])


def test_search_empty_payload():
    parsed = P.parse_search([], "USD")
    assert parsed == {"results": [], "total_count": None, "has_next": False, "place": None, "is_single_hotel": False}
    assert P.parse_search(None, "USD")["results"] == []


# ---- hotels/details + prices -----------------------------------------------------------

def test_entity_record(entity):
    assert entity["id"] == TOKEN and entity["name"] == "The People"
    assert entity["location"]["address"] == "17 Bd Morland, 75004 Paris, France"
    assert entity["location"]["neighborhood"] == "Arsenal"
    assert [a["name"] for a in entity["location"]["areas"]] == ["Paris Metropolitan Area", "Paris", "Arsenal"]
    assert entity["location"]["bounds"]["north"] > entity["location"]["bounds"]["south"]
    assert entity["location"]["maps_link"].startswith("https://maps.google.com/")
    assert entity["contact"]["phone"] == "+33 1 81 22 40 88"
    assert entity["description"].startswith("Sleek dorms")
    assert len(entity["description_paragraphs"]) == 3
    assert entity["rating"] == 4.0 and entity["reviews_count"] == 1944
    assert entity["reviews"]["source_ratings"][0]["name"] == "Tripadvisor"
    assert entity["reviews"]["source_ratings"][0]["reviews_count"] == 152
    assert [s["name"] for s in entity["reviews"]["sources"]][:2] == ["Google", "Tripadvisor"]
    assert entity["attributes"] == [{"group": "Crowd", "name": "LGBTQ+ friendly"}]
    assert entity["ids"]["place_id"] == "ChIJjRraPPlx5kcRHCEo0fZXGmU"
    assert entity["ids"]["maps_cid"] == "15524462075315628512"
    assert entity["photo_categories"][0] == {"name": "bedroom", "photos_count": 90,
                                             "thumbnail": entity["photo_categories"][0]["thumbnail"]}
    assert any(c["name"] == "from_visitors" and c["photos_count"] == 1035 for c in entity["photo_categories"])


def test_entity_price_and_offers(entity):
    price = entity["price"]
    assert price["currency"] == "INR"
    assert price["nightly"]["amount"] == 6892.62 and price["nightly"]["display"] == "₹6,893"
    assert price["base_price"] == 6265.19 and price["taxes"] == 627.43 and price["fees"] == 0
    assert price["total_with_taxes_and_fees"] == 6892.62
    assert "typical_range" not in price   # [7][1][0][16] is not a reliable range (2026-11-02)
    assert price["deal"] == "42% less than usual"
    offers = entity["offers"]
    assert len(offers) == 12
    own = offers[0]
    assert own["vendor"] == "The People" and own["is_official_site"] is True
    assert own["nightly_price"]["amount"] == 6892.62 and own["nightly_price"]["currency"] == "INR"
    assert own["link"].startswith("https://www.google.com/travel/lodging/clk?")
    assert own["partner_link"].startswith("https://secure-hotel-tracker.com/")
    assert offers[1]["vendor"] == "Goibibo.com" and offers[1]["is_official_site"] is False
    assert offers[1]["total_price"]["amount"] == 7064


def test_entity_amenities(entity):
    groups = entity["amenity_groups"]
    assert {g["group"] for g in groups} >= {"Internet", "Rooms", "Pools", "Pets", "Services"}
    wifi = next(a for a in groups if a["name"] == "Wi-Fi" and a["group"] == "Internet")
    assert wifi == {"group": "Internet", "name": "Wi-Fi", "note": "free", "is_available": True}
    assert next(a for a in groups if a["name"] == "No pools")["is_available"] is False
    assert next(a for a in groups if a["name"] == "Breakfast" and a["group"] == "Food & drink")["note"] == "extra charge"


def test_amenities_popular_strip_only():
    html = fixture("entity_page_amenities_the_people_paris_marais.html")
    popular_only = html[:html.find(">Amenities</h2>")]
    out = P.parse_amenities(popular_only)
    assert [a["name"] for a in out] == ["Wi-Fi", "Breakfast", "Parking", "Restaurant"]
    assert P.parse_amenities("") == [] and P.parse_amenities(None) == []


def test_entity_not_found_shell():
    assert P.parse_entity([], fixture("entity_page_not_found.html")) is None
    assert P.parse_entity(None) is None


# ---- hotels/reviews --------------------------------------------------------------------

def test_reviews():
    parsed = P.parse_reviews(fixture("reviews_rpc_the_people_paris_marais.json.gz"))
    assert len(parsed["reviews"]) == 10
    assert parsed["next_token"].startswith("CjEIARIp") and parsed["next_token"].endswith(":10")
    first = parsed["reviews"][0]
    assert first["source"] == "Google"
    assert first["author"]["name"] == "Daphne Stibbe"
    assert first["author"]["link"].startswith("https://www.google.com/maps/contrib/")
    assert first["rating"] == 2 and first["rating_max"] == 5
    assert first["date_text"] == "3 months ago"
    assert first["visited"] == {"year": 2026, "month": 7} and first["visited_text"] == "Visited in July"
    assert first["text"].startswith("we often stay as a family") and "&#39;" not in first["text"] and "<br>" not in first["text"]
    assert "\n" in first["text"]
    assert first["aspects"][0] == {"aspect": "rooms", "rating": 2, "rating_max": 5}
    assert [a["aspect"] for a in first["aspects"]] == ["rooms", "service", "location"]
    assert first["owner_response"]["text"].startswith("Thank you for taking the time")
    assert first["owner_response"]["date_text"] == "a month ago"
    assert first["id"].startswith("Ci9")
    assert P.parse_reviews([]) == {"reviews": [], "next_token": None}


# ---- hotels/photos ---------------------------------------------------------------------

def test_photos():
    parsed = P.parse_photos(fixture("photos_rpc_the_people_paris_marais.json.gz"),
                            fixture("photo_categories_rpc_the_people_paris_marais.json.gz"))
    assert len(parsed["photos"]) == 15
    photo = parsed["photos"][0]
    assert photo["link"].startswith("https://lh3.googleusercontent.com/")
    assert photo["original_link"].endswith("=s0")
    assert photo["width"] == 4024 and photo["height"] == 6048
    assert photo["uploaded_on"] == "2022-03-28"
    assert photo["author"]["name"] == "The People Paris Marais"
    assert photo["author"]["link"].startswith("https://maps.google.com/maps/contrib/")
    categories = {c["name"]: c for c in parsed["categories"]}
    assert categories["bedroom"]["photos_count"] == 90 and categories["food_and_drink"]["photos_count"] == 211
    assert categories["from_visitors"]["photos_count"] == 1035 and categories["by_owner"]["photos_count"] == 36
    assert P.photos_total(parsed["categories"]) == 1071
    assert P.parse_photos(None, None) == {"photos": [], "categories": []}


# ---- places ---------------------------------------------------------------------------

def test_autocomplete():
    out = P.parse_autocomplete(fixture("autocomplete_rpc_hotels_in_lisb.json.gz"))
    assert out[0] == {"text": "hotels in lisbon", "completion": "on"}
    assert len(out) >= 5
    assert P.parse_autocomplete(None) == []


def test_price_trends():
    out = P.parse_price_trends(fixture("price_trends_rpc_paris.json.gz"), "USD")
    assert len(out["months"]) == 12
    jan = out["months"][0]
    assert jan["month"] == "January" and jan["month_number"] == 1
    assert jan["price_level"] == 3 and jan["crowd_level"] == 4
    assert jan["price_from"] == {"amount": 67.0, "currency": "USD", "display": "$67"}
    assert jan["price_to"]["amount"] == 176.0
    assert jan["high_temperature"] == 47 and jan["low_temperature"] == 39 and jan["rainy_days"] == 4
    assert out["description"].startswith("Paris is a year-round destination")
    assert P.parse_price_trends(None) == {"months": [], "description": None}


# ---- helpers ---------------------------------------------------------------------------

@pytest.mark.parametrize("display,amount", [
    ("$1,234", 1234.0), ("₹6,893", 6893.0), ("€1.234,50", 1234.5), ("1 234 €", 1234.0), ("$67", 67.0),
    ("free", None), (None, None), ("IDR147K", 147000.0), ("IDR1.2M", 1200000.0),
])
def test_amount_from_display(display, amount):
    assert P._amount_from_display(display) == amount
