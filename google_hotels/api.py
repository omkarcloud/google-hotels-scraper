"""The /google-hotels/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs). Every endpoint caches inside
(cache.cached_call keyed on the validated params, TTLs in cache_config);
hotels/details and hotels/prices share ONE cached entity-page parse per
(hotel, stay, currency, locale), so a client hitting both pays one fetch.
"""
from datetime import date

from cache import cached_call
from google_hotels import cache_config as ttl
from google_hotels import parsers, refs
from google_hotels.fetch import (RPC_AUTOCOMPLETE, RPC_PHOTO_CATEGORIES, RPC_PHOTOS, RPC_PRICE_TRENDS, RPC_REVIEWS,
                                 RPC_SEARCH, GoogleHotelsBadRequest, GoogleHotelsNotFound, entity_page, rpc)

PHOTO_THUMB = [253, 253]
PHOTO_CATEGORY_THUMB = [152, 152]


def _nights(check_in, check_out):
    return (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days


def _stay(check_in, check_out):
    ci, co = date.fromisoformat(check_in), date.fromisoformat(check_out)
    return [None, [[ci.year, ci.month, ci.day], [co.year, co.month, co.day], _nights(check_in, check_out)],
            None, None, None, [None, 0]]


def _occupancy(adults, children_ages):
    travellers = [[3] for _ in range(adults)] + [[2, age] for age in (children_ages or [])]
    return [travellers, len(children_ages or [])]


def _stay_summary(check_in, check_out, adults, children_ages, currency):
    return {"check_in": check_in, "check_out": check_out, "nights": _nights(check_in, check_out),
            "adults": adults, "children_ages": children_ages or [], "currency": currency}


# ---- hotels/search ---------------------------------------------------------------

def _search_request(query, kind, place, stay, occupancy, currency, sort, hotel_class, amenities,
                    min_price, max_price, min_rating, page):
    options = [None] * 12
    if amenities:
        options[0] = list(amenities)
    if hotel_class:
        options[1] = [int(c) for c in hotel_class]
    if sort:
        options[4] = sort
    options[6] = currency
    options[11] = [1]
    settings = [options]
    if min_price is not None or max_price is not None or min_rating:
        band = [int(min_price) if min_price else None, int(max_price) if max_price else None]
        settings += [None, [], [None, band, 1] if (min_price or max_price) else None, min_rating or None]
    where = [None, [[None, None, None, None, None, place["id"], place.get("name")]]] if place else None
    return [query, [kind, occupancy, [where, stay], None, settings],
            [None, refs.search_cursor(page), None, None, None, None, 13, None, 0], None, 1]


def _hotels_search(query, check_in, check_out, adults, children_ages, currency, language, country, sort,
                   min_price, max_price, hotel_class, min_rating, amenities, property_type, page):
    stay = _stay(check_in, check_out)
    occupancy = _occupancy(adults, children_ages)
    sort_code = refs.SORTS.get(sort)
    sent_query = query
    if property_type == refs.PROPERTY_TYPES["vacation_rental"]:
        # The RPC's kind flag alone does not switch to rentals (verified
        # 2026-11-01: kind 2 + the resolved place still lists hotels); the
        # query wording does, exactly as on the site.
        sent_query = refs.rentals_query(query)
    payload = rpc(RPC_SEARCH, _search_request(sent_query, property_type, None, stay, occupancy, currency, sort_code,
                                              hotel_class, amenities, min_price, max_price, min_rating, page),
                  language, country)
    parsed = parsers.parse_search(payload, currency)
    results = parsed["results"]
    total = parsed["total_count"]
    has_next = parsed["has_next"] and len(results) >= refs.PAGE_SIZE
    total_pages = None
    if total is not None:
        total_pages = max(1, -(-min(total, refs.MAX_RESULTS) // refs.PAGE_SIZE))
        has_next = page < total_pages and len(results) > 0
    return {
        "query": query,
        "place": parsed["place"],
        "property_type": next((k for k, v in refs.PROPERTY_TYPES.items() if v == property_type), "hotel"),
        "stay": _stay_summary(check_in, check_out, adults, children_ages, currency),
        "sort": sort,
        "is_single_hotel": parsed["is_single_hotel"],
        "results": results,
        "pagination": {"page": page, "items_per_page": refs.PAGE_SIZE, "has_next": has_next,
                       "total_pages": total_pages, "total_count": total},
    }


def hotels_search(**data):
    return cached_call("google-hotels.search", data, _hotels_search, ttl.SEARCH_CACHE)


# ---- the shared entity page record -----------------------------------------------

def _entity_record(hotel, check_in, check_out, adults, children_ages, currency, language, country):
    ts = refs.ts_param(check_in, check_out, adults=adults, children_ages=children_ages, currency=currency)
    html, ds1 = entity_page(hotel, "prices", ts=ts, language=language, country=country)
    record = parsers.parse_entity(ds1, html, currency)
    if record is None or not record.get("name"):
        raise GoogleHotelsNotFound(f"no Google Hotels entity {hotel}")
    return record


def _record(data):
    return cached_call("google-hotels.entity", data, _entity_record, ttl.DETAILS_CACHE)


def hotel_details(**data):
    """Everything on the hotel's page except the vendor rate ladder
    (hotels/prices): facts, location, contact, amenities, nearby, review
    summary, images and the headline price for the stay."""
    record = _record(data)
    out = {k: v for k, v in record.items() if k != "offers"}
    out["offers_count"] = len(record.get("offers") or [])
    out["stay"] = _stay_summary(data["check_in"], data["check_out"], data["adults"], data["children_ages"],
                                data["currency"])
    return out


def hotel_prices(**data):
    """The rate ladder for the stay: every booking site Google lists with its
    nightly and total price, deeplink and partner URL, plus the headline
    price, taxes split and deal."""
    record = _record(data)
    offers = record.get("offers") or []
    priced = [o for o in offers if o.get("nightly_price") and o["nightly_price"].get("amount") is not None]
    cheapest = min(priced, key=lambda o: o["nightly_price"]["amount"]) if priced else None
    return {
        "id": record["id"],
        "name": record["name"],
        "link": record["link"],
        "stay": _stay_summary(data["check_in"], data["check_out"], data["adults"], data["children_ages"],
                              data["currency"]),
        "price": record.get("price"),
        "cheapest_offer": cheapest,
        "offers": offers,
        "offers_count": len(offers),
    }


# ---- hotels/reviews ------------------------------------------------------------------

def _hotel_reviews(hotel, sort, limit, next_token, language, country):
    inner = [None, None, None, limit, sort, None, None, "", hotel, next_token or "", None, [[]], None, ""]
    try:
        payload = rpc(RPC_REVIEWS, inner, language, country)
    except GoogleHotelsBadRequest:
        # The schema already bounds every other argument: Google's
        # INVALID_ARGUMENT here means the token names no hotel (or the
        # continuation token belongs to another hotel / sort).
        raise GoogleHotelsNotFound(f"no Google Hotels entity {hotel} (or a next_token from another call)")
    parsed = parsers.parse_reviews(payload)
    sort_name = next((k for k, v in refs.REVIEW_SORTS.items() if v == sort), "most_helpful")
    return {
        "id": hotel,
        "link": refs.hotel_link(hotel) + "/reviews",
        "sort": sort_name,
        "count": len(parsed["reviews"]),
        "reviews": parsed["reviews"],
        "next_token": parsed["next_token"],
        "has_next": bool(parsed["next_token"]) and len(parsed["reviews"]) >= limit,
    }


def hotel_reviews(**data):
    return cached_call("google-hotels.reviews", data, _hotel_reviews, ttl.REVIEWS_CACHE)


# ---- hotels/photos -------------------------------------------------------------------

def _hotel_photos(hotel, language, country):
    # Categories first: an unknown token is an instant INVALID_ARGUMENT
    # there, where the gallery RPC would answer INTERNAL (13) and be retried.
    try:
        categories = rpc(RPC_PHOTO_CATEGORIES, [None, None, None, PHOTO_CATEGORY_THUMB, hotel], language, country)
    except GoogleHotelsBadRequest:
        raise GoogleHotelsNotFound(f"no Google Hotels entity {hotel}")
    gallery = rpc(RPC_PHOTOS, [hotel, PHOTO_THUMB, [], None, 20, 1], language, country)
    parsed = parsers.parse_photos(gallery, categories)
    total = parsers.photos_total(parsed["categories"])
    return {
        "id": hotel,
        "link": refs.hotel_link(hotel) + "/photos",
        "count": len(parsed["photos"]),
        "total_count": total,
        "photos": parsed["photos"],
        "categories": parsed["categories"],
    }


def hotel_photos(**data):
    return cached_call("google-hotels.photos", data, _hotel_photos, ttl.PHOTOS_CACHE)


# ---- places/autocomplete -------------------------------------------------------------

def _places_autocomplete(query, language, country):
    suggestions = parsers.parse_autocomplete(rpc(RPC_AUTOCOMPLETE, [query, "", 1, 1, None, 30], language, country))
    return {"query": query, "count": len(suggestions), "suggestions": suggestions}


def places_autocomplete(**data):
    return cached_call("google-hotels.autocomplete", data, _places_autocomplete, ttl.AUTOCOMPLETE_CACHE)


# ---- places/price-trends -------------------------------------------------------------

def _places_price_trends(query, currency, language, country):
    payload = rpc(RPC_PRICE_TRENDS, [[query, None, None, [None, None, None, currency]], 2], language, country)
    parsed = parsers.parse_price_trends(payload, currency)
    return {"query": query, "currency": currency, **parsed}


def places_price_trends(**data):
    return cached_call("google-hotels.price_trends", data, _places_price_trends, ttl.PRICE_TRENDS_CACHE)
