"""Reference resolvers, wire tables and the two protobuf URL params for
/google-hotels/*. Pure (no network).

ONE param per input (tripadvisor QueryOrIdField convention): `hotel`
accepts a bare Google Hotels entity token (ChkInMKgie3-lY1lGg0vZy8xMXJ0X3M0dno0EAE)
OR any Google Hotels entity link
(https://www.google.com/travel/hotels/entity/<token>[/prices|/reviews|…]?…,
any google.<tld> host, an optional /<slug>/ before "entity"). Resolvers
raise ValueError with a user-facing message (RefField -> 400).

Wire tables (captured 2026-10-30 by driving www.google.com/travel/search
and decoding the `ts` URL protobuf after each UI action, then replaying
the AtySUc search RPC with the same values):
  sort            5.1.5 of `ts` / opts[4] of the RPC: 3 lowest price,
                  8 highest rating, 13 most reviewed (verified by result
                  order); relevance = unset
  guest rating    5.5 of `ts` / f5[4] of the RPC: 7 = 3.5+, 8 = 4.0+, 9 = 4.5+
  hotel class     5.1.2 / opts[1]: packed ints 2..5
  amenities       5.1.1 / opts[0]: Google's own filter ids (6 pool, 10 spa
                  verified by the chips; the rest are the ids Google's
                  hotel filter UI sends, the same table every SerpApi-shaped
                  client publishes)
  price cap       5.4.2.2 / f5[3] = [None, [min, max], 1]
  occupancy       2 of `ts` / req[1][1]: one [3] per adult, [2, age] per
                  child, then the child count
  kind            1 of `ts` / req[1][0]: 1 hotels, 2 vacation rentals
                  (vacation rentals also need the resolved place id, which
                  a hotels search echoes back)

Pagination: the SSR page takes `qs` = proto{2: base64(proto{1: offset}),
7: 13}; the RPC takes the same base64(proto{1: offset}) string as
req[2][1] ("CBI=" = offset 18, Google's own page step). Pages here are
20 wide, offset = (page - 1) * 20, which the server honours directly.
"""
import base64
import re
from urllib.parse import urlparse

SITE = "https://www.google.com"
PAGE_SIZE = 20
MAX_RESULTS = 15000          # Google's own cap on a place search ("1 - 20 of 15,000")
MAX_PAGE = MAX_RESULTS // PAGE_SIZE

TOKEN_RE = re.compile(r"^Ch[A-Za-z0-9_-]{14,}$")
_LINK_TOKEN_RE = re.compile(r"/travel/hotels/(?:[^/?#]+/)?entity/(Ch[A-Za-z0-9_-]{14,})")

SORTS = {"relevance": None, "lowest_price": 3, "highest_rating": 8, "most_reviewed": 13}
GUEST_RATINGS = {"3.5": 7, "4": 8, "4.0": 8, "4.5": 9}
HOTEL_CLASSES = ("2", "3", "4", "5")
PROPERTY_TYPES = {"hotel": 1, "vacation_rental": 2}

# Public amenity names -> Google's hotel-filter ids.
AMENITY_FILTERS = {
    "free_parking": 1, "parking": 3, "indoor_pool": 4, "outdoor_pool": 5, "pool": 6,
    "fitness_center": 7, "restaurant": 8, "free_breakfast": 9, "spa": 10, "beach_access": 11,
    "child_friendly": 12, "bar": 15, "pet_friendly": 19, "room_service": 22, "free_wifi": 35,
    "air_conditioned": 40, "all_inclusive": 52, "wheelchair_accessible": 53, "ev_charger": 61,
}

REVIEW_SORTS = {"most_helpful": 1, "most_recent": 2, "highest_rating": 3, "lowest_rating": 4}
REVIEWS_PAGE_MAX = 50        # the ocp93e RPC answers [3] (INVALID_ARGUMENT) above this

# Google's nearby-place categories (hotel details "nearby" block, kind ids
# seen 2026-10-30) and the travel modes of their durations.
NEARBY_KINDS = {1: "top_sight", 2: "transit", 3: "airport", 4: "restaurant", 5: "shopping", 6: "restaurant"}
TRAVEL_MODES = {0: "driving", 1: "transit", 2: "walking", 3: "driving", 7: "none"}


def _host_is_google(url):
    host = (urlparse(url).hostname or "").lower()
    labels = host.split(".")
    return "google" in labels


def resolve_hotel(value):
    """Bare entity token or a Google Hotels entity link -> the token."""
    value = (value or "").strip()
    if TOKEN_RE.match(value):
        return value
    if value.startswith(("http://", "https://", "//")):
        url = value if not value.startswith("//") else "https:" + value
        if not _host_is_google(url):
            raise ValueError("Must be a google.com/travel/hotels link.")
        match = _LINK_TOKEN_RE.search(url)
        if match:
            return match.group(1)
        raise ValueError("Must be a Google Hotels entity link "
                         "(https://www.google.com/travel/hotels/entity/<token>).")
    raise ValueError("Must be a Google Hotels entity token (ChkI…EAE) or an entity link "
                     "(https://www.google.com/travel/hotels/entity/<token>).")


def hotel_link(token):
    return f"{SITE}/travel/hotels/entity/{token}"


_PLACE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:hotels?|stays?|accommodations?|places to stay)\s+)?(?:in|near|around)\s+", re.I)
_RENTAL_WORD_RE = re.compile(r"\b(?:rentals?|apartments?|villas?|cottages?|cabins?|houses?|homes?)\b", re.I)


def rentals_query(query):
    """'hotels in paris' / 'near Times Square' -> 'vacation rentals in
    paris' / 'vacation rentals in Times Square': the wording that makes the
    search RPC list vacation rentals (its kind flag alone does not,
    verified 2026-11-01). Whole words only, so "lighthouse" or "warehouse
    district" is still rewritten."""
    if _RENTAL_WORD_RE.search(query):
        return query
    place = _PLACE_PREFIX_RE.sub("", query)
    return f"vacation rentals in {place}" if place else query


def children_ages_ref(value):
    """'5, 12' -> [5, 12]; each age 0-17, at most 8 children."""
    ages = []
    for raw in str(value).split(","):
        raw = raw.strip()
        if not raw:
            continue
        if not raw.isdigit() or int(raw) > 17:
            raise ValueError("Children ages must be whole numbers from 0 to 17, comma separated (e.g. 5,12).")
        ages.append(int(raw))
    if len(ages) > 8:
        raise ValueError("At most 8 children.")
    return ages or None


# ---- protobuf wire helpers (the `ts` / `qs` URL params and the RPC cursor) -----

def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def pb_field(number, value):
    """One protobuf field: int -> varint, bytes/str -> length-delimited."""
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    if isinstance(value, str):
        value = value.encode("utf-8")
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def pb_packed(number, values):
    return pb_field(number, b"".join(_varint(v) for v in values))


def b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def search_cursor(page):
    """The RPC continuation / `qs` inner token for a 1-based page."""
    if page <= 1:
        return None
    return base64.b64encode(pb_field(1, (page - 1) * PAGE_SIZE)).decode()


def qs_param(page):
    """The SSR search page's `qs` URL param for a 1-based page (None for page 1)."""
    cursor = search_cursor(page)
    if cursor is None:
        return None
    return b64url(pb_field(2, cursor) + pb_field(7, 13))


def _date(iso):
    year, month, day = (int(x) for x in iso.split("-"))
    return pb_field(1, year) + pb_field(2, month) + pb_field(3, day)


def ts_param(check_in, check_out, adults=2, children_ages=None, currency="USD", kind=1,
             place=None, sort=None, hotel_classes=None, amenities=None, max_price=None,
             min_price=None, guest_rating=None):
    """The `ts` URL protobuf of a /travel/search or an entity page: the stay,
    occupancy, currency and (for the search page) kind / place / filters."""
    travellers = b"".join(pb_field(1, pb_field(1, 3)) for _ in range(adults))
    for age in children_ages or ():
        travellers += pb_field(1, pb_field(1, 2) + pb_field(2, age))
    occupancy = travellers + pb_field(2, len(children_ages or ()))
    stay = pb_field(2, pb_field(2, pb_field(1, _date(check_in)) + pb_field(2, _date(check_out)) + pb_field(3, 1))
                    + pb_field(6, pb_field(2, 0)))
    where = b""
    if place:
        where = pb_field(1, pb_field(2, pb_field(6, place["id"]) + pb_field(7, place["name"] or "")))
    options = b""
    if amenities:
        options += pb_packed(1, amenities)
    if hotel_classes:
        options += pb_packed(2, hotel_classes)
    if sort:
        options += pb_field(5, sort)
    options += pb_field(7, currency) + pb_field(12, pb_field(1, 1))
    settings = pb_field(1, options)
    if max_price or min_price:
        band = (pb_field(1, int(min_price)) if min_price else b"") + (pb_field(2, int(max_price)) if max_price else b"")
        settings += pb_field(4, pb_field(2, band) + pb_field(3, 1))
    if guest_rating:
        settings += pb_field(5, guest_rating)
    return b64url(pb_field(1, kind) + pb_field(2, occupancy) + pb_field(3, where + stay) + pb_field(5, settings))
