"""Google Hotels raw payloads -> clean dicts. Pure functions, no I/O.

Positions were mapped 2026-10-30/31 from live captures (scratchpad
capture*/, fixtures/ here, dated in each parser's docstring). Every reader
goes through `_at()` so a missing / reshaped branch yields None instead of
an exception: the site reshuffles these positional arrays without notice.

Raw shapes:
  * a HOTEL RECORD (the same positional array on three surfaces: each
    entry of the AtySUc search payload under key "397419284", the matched
    hotel of a hotel-name search under "441552390", and `ds:1[0]` of a
    server-rendered entity page):
      [1] name  [2] place block (coords, address, phone, maps links,
      neighborhood, check-in/out times, nearby, area hierarchy, website,
      types, bounds, country)  [3] [class label, stars]  [5] images
      [6][2] price block (headline nightly / total, taxes split, deal, price
      range, vendor ladder, currency)  [7] reviews block (rating, count,
      histogram, source summaries, topics, sources)  [9] maps feature id
      [10] amenity flags + eco badge  [11] description  [12] thumbnail
      [14] 1 hotel / 2 vacation rental  [19] vacation-rental block
      [20] entity token  [25] Maps CID  [26][4] Places id  [38] photo
      categories (entity page only)
  * REVIEWS (ocp93e): payload[0][0] = reviews, payload[0][5] = next token
  * PHOTOS (pSDzMb): payload[0] = photo groups; CATEGORIES (zM1L7d):
    payload[0] = [[id, _, _, count, [thumb]], ...]
  * AUTOCOMPLETE (mejVKc): payload[0] = suggestion rows
  * PRICE TRENDS (axSywf): payload[1][1] = 12 month rows, payload[1][3] text
"""
import html as html_lib
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from google_hotels import refs

FEATURE_ID_RE = re.compile(r"^0x[0-9a-f]+:0x[0-9a-f]+$")
_PRICE_RE = re.compile(r"[\d][\d,.\s]*")
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_WS_RE = re.compile(r"\s+")

# Review aspect ids (Google hotel reviews rate exactly these three).
REVIEW_ASPECTS = {1: "rooms", 4: "service", 5: "location"}
PROPERTY_KINDS = {1: "hotel", 2: "vacation_rental"}
# Photo category ids (zM1L7d rows / the entity page's [38] block), labels
# read off the hotel page's photo tiles and the gallery tabs on 2026-11-02
# (Bellagio: tiles Exterior / Food & Drink / Bedroom, gallery tabs All /
# From visitors / By owner / 360° view). The id-less rows are the gallery
# tabs: [None, 1] from visitors, [None, 0] by owner, [None, None, 1] 360°.
PHOTO_CATEGORIES = {2: "bedroom", 3: "bathroom", 4: "exterior", 5: "food_and_drink"}
AMENITY_GROUPS_ORDER = ("Popular amenities",)


# ---- small readers ----------------------------------------------------------------

def _at(obj, *path, default=None):
    """Positional get that never raises: _at(rec, 6, 2, 1, 0)."""
    cur = obj
    for key in path:
        if isinstance(cur, list):
            if not isinstance(key, int) or key >= len(cur) or key < -len(cur):
                return default
            cur = cur[key]
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return default
        if cur is None:
            return default
    return cur


def _text(value):
    """A display string: entities decoded, tags dropped, Google's narrow
    no-break spaces ("3:00 PM") folded to plain spaces."""
    if isinstance(value, str):
        if "<" in value:
            value = _TAG_RE.sub(" ", _BR_RE.sub("\n", value))
        value = html_lib.unescape(value).replace(" ", " ").replace("\xa0", " ")
        value = _WS_RE.sub(" ", value).strip()
        return value or None
    return None


def _html_text(value):
    """Review text: keep paragraph breaks, drop tags and entities."""
    if not isinstance(value, str):
        return None
    value = _BR_RE.sub("\n", value)
    value = _TAG_RE.sub("", value)
    value = html_lib.unescape(value)
    lines = [_WS_RE.sub(" ", line).strip() for line in value.split("\n")]
    text = "\n".join(line for line in lines if line)
    return text or None


def _num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _int(value):
    value = _num(value)
    return int(value) if value is not None else None


def _round2(value):
    value = _num(value)
    return round(float(value), 2) if value is not None else None


def _amount_from_display(display):
    """'$1,234' / '₹6,893' / '€1.234,50' / 'IDR147K' -> 1234.0 (best effort,
    display only; Google abbreviates large currencies with K / M)."""
    if not isinstance(display, str):
        return None
    cleaned = display.replace(" ", "").replace("\xa0", "")
    match = _PRICE_RE.search(cleaned)
    if not match:
        return None
    raw = match.group(0).strip()
    suffix = cleaned[match.end():match.end() + 1].upper()
    scale = {"K": 1000, "M": 1000000}.get(suffix, 1)
    if "," in raw and "." in raw:
        raw = raw.replace(",", "") if raw.rfind(".") > raw.rfind(",") else raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        parts = raw.split(",")
        raw = raw.replace(",", "") if all(len(p) == 3 for p in parts[1:]) else raw.replace(",", ".")
    try:
        return float(raw.replace(" ", "")) * scale
    except ValueError:
        return None


def _money(block, currency):
    """A price triple [display, _, amount, _, rounded] -> {amount, display}."""
    if not isinstance(block, list) or not block:
        return None
    display = _text(block[0]) if isinstance(block[0], str) else None
    amount = _round2(_at(block, 2))
    if amount is None:
        amount = _round2(_at(block, 4)) if _num(_at(block, 4)) is not None else _amount_from_display(display)
    if amount is None and display is None:
        return None
    return {"amount": amount, "currency": currency, "display": display}


def _absolute(link):
    if not isinstance(link, str) or not link:
        return None
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return refs.SITE + link
    return link


def _image_url(url):
    return _absolute(url) if isinstance(url, str) else None


def _original_image(url):
    """lh3 photo URL with its size suffix replaced by =s0 (the original)."""
    if not isinstance(url, str) or "googleusercontent.com" not in url:
        return _image_url(url)
    base = url.rsplit("=", 1)[0] if re.search(r"=[a-z0-9-]+$", url) else url
    return _absolute(base + "=s0")


def _iso_date(parts):
    """[2026, 12, 1] -> '2026-12-01'."""
    if isinstance(parts, list) and len(parts) >= 3 and all(isinstance(p, int) for p in parts[:3]):
        return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    return None


def _epoch_iso(seconds):
    seconds = _num(seconds)
    if not seconds:
        return None
    try:
        return datetime.fromtimestamp(float(seconds), tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def _walk_key(obj, key, out):
    """Collect every value stored under dict key `key` anywhere in obj."""
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj[key])
        for value in obj.values():
            _walk_key(value, key, out)
    elif isinstance(obj, list):
        for value in obj:
            _walk_key(value, key, out)
    return out


# ---- the hotel record -----------------------------------------------------------------

def _nearby(block):
    """[[kind, [kind, _, [[name, _, [[mode, '8 min'], ...]], ...]]], ...]"""
    out = []
    for group in block or []:
        kind = _int(_at(group, 0))
        for place in _at(group, 1, 2) or []:
            name = _text(_at(place, 0))
            if not name:
                continue
            travel = []
            for leg in _at(place, 2) or []:
                duration = _text(_at(leg, 1))
                if duration:
                    travel.append({"mode": refs.TRAVEL_MODES.get(_int(_at(leg, 0)), "unknown"), "duration": duration})
            out.append({"name": name, "kind": refs.NEARBY_KINDS.get(kind, "place"), "travel_times": travel})
    return out


def _types(block):
    """[[['gcid:hostel', True], ['gcid:bar', False]]] -> primary + all."""
    primary, all_types = None, []
    for row in _at(block, 0) or []:
        gcid = _at(row, 0)
        if not isinstance(gcid, str):
            continue
        label = gcid.split(":", 1)[-1]
        all_types.append(label)
        if _at(row, 1) is True and primary is None:
            primary = label
    return primary or (all_types[0] if all_types else None), all_types


def _images(block):
    """[5][1] = [[_, [url, h, w, _, [source kind, id], ...]], ...]"""
    out = []
    for item in _at(block, 1) or []:
        url = _at(item, 1, 0)
        if not isinstance(url, str):
            continue
        source = _at(item, 1, 4, 1)
        out.append({
            "link": _image_url(url),
            "original_link": _original_image(url),
            "source_link": _absolute(source) if isinstance(source, str) and source.startswith("http") else None,
        })
    return out


def _rating_histogram(block):
    out = []
    for row in block or []:
        stars = _int(_at(row, 0))
        if stars is None:
            continue
        out.append({"stars": stars, "percent": _int(_at(row, 1)), "count": _int(_at(row, 2))})
    return out


def _review_topics(block):
    """[_, sentiment, mentions, _, name, group, short name, positive, negative]"""
    out = []
    for row in block or []:
        name = _text(_at(row, 4))
        if not name:
            continue
        out.append({
            "name": name,
            "mentions": _int(_at(row, 2)),
            "positive": _int(_at(row, 7)),
            "negative": _int(_at(row, 8)),
            "sentiment": _round2(_at(row, 1)),
        })
    return out


def _review_sources(block):
    out = []
    for row in block or []:
        name = _text(_at(row, 0))
        if not name:
            continue
        entry = {"name": name, "link": _absolute(_at(row, 1)) if isinstance(_at(row, 1), str) else None}
        if entry not in out:
            out.append(entry)
    return out


def _source_summaries(block):
    """[7][4]: per third-party source: [name, icon, [score, max], count, [sample reviews], link, id]"""
    out = []
    for row in block or []:
        name = _text(_at(row, 0))
        if not name:
            continue
        out.append({
            "name": name,
            "rating": _round2(_at(row, 2, 0)),
            "rating_max": _int(_at(row, 2, 1)),
            "reviews_count": _int(_at(row, 3)),
            "link": _absolute(_at(row, 5)) if isinstance(_at(row, 5), str) else None,
        })
    return out


def _reviews_block(block):
    if not isinstance(block, list):
        return {"rating": None, "reviews_count": None, "histogram": [], "topics": [], "sources": [],
                "source_ratings": []}
    return {
        "rating": _round2(_at(block, 0, 0)),
        "reviews_count": _int(_at(block, 0, 1)),
        "histogram": _rating_histogram(_at(block, 1, 0)),
        "topics": _review_topics(_at(block, 9)),
        "sources": _review_sources(_at(block, 14)),
        "source_ratings": _source_summaries(_at(block, 4)),
    }


def _partner_link(clk_path):
    """The partner URL inside a /travel/lodging/clk?pcurl=… redirect."""
    if not isinstance(clk_path, str):
        return None
    try:
        query = parse_qs(urlparse(clk_path).query)
    except ValueError:
        return None
    partner = query.get("pcurl", [None])[0]
    return partner if partner and partner.startswith("http") else None


def _offers(block, currency):
    """[6][2][21]: the vendor ladder. entry[0] = [vendor, vendor id, redirect
    path, [logo], _, official], entry[12] = [.., .., .., .., nightly, total,
    ...]"""
    out = []
    for entry in block or []:
        head = _at(entry, 0)
        name = _text(_at(head, 0))
        if not name:
            continue
        redirect = _at(head, 2)
        out.append({
            "vendor": name,
            "vendor_id": _int(_at(head, 1)),
            "is_official_site": _at(head, 5) == 1,
            "nightly_price": _money(_at(entry, 12, 4), currency),
            "total_price": _money(_at(entry, 12, 5), currency),
            "link": _absolute(redirect) if isinstance(redirect, str) else None,
            "partner_link": _partner_link(redirect),
            "logo": _image_url(_at(head, 3, 0)),
        })
    return out


def _price_block(block, currency):
    """[6][2] of a record: headline nightly / total, taxes split, deal and range."""
    if not isinstance(block, list):
        return None
    currency = _at(block, 15) if isinstance(_at(block, 15), str) else currency
    breakdown = _at(block, 44)
    price_range = _at(block, 7, 1, 0, 16)
    deal = _text(_at(block, 7, 3, 3, 0))
    nightly = _money(_at(block, 1), currency)
    total = _money(_at(block, 9), currency)
    if nightly is None and total is None and not isinstance(breakdown, list):
        return None
    return {
        "currency": currency,
        "nightly": nightly,
        "total": total,
        # [44] = [base, taxes, fees (resort / service), total] for the whole
        # stay (Bellagio 2026-11-02: 253.77 + 39.14 + 54.99 = 347.91)
        "base_price": _round2(_at(breakdown, 0)) if isinstance(breakdown, list) else None,
        "taxes": _round2(_at(breakdown, 1)) if isinstance(breakdown, list) else None,
        "fees": _round2(_at(breakdown, 2)) if isinstance(breakdown, list) else None,
        "total_with_taxes_and_fees": _round2(_at(breakdown, 3)) if isinstance(breakdown, list) else None,
        "deal": deal,
        "typical_range": {
            "low": _text(_at(price_range, 0)),
            "typical": _text(_at(price_range, 1)),
            "high": _text(_at(price_range, 2)),
        } if isinstance(price_range, list) and _text(_at(price_range, 0)) else None,
        "check_in": _iso_date(_at(block, 8, 0)),
        "check_out": _iso_date(_at(block, 8, 1)),
    }


def _amenity_flags(block):
    """[10][8] = [[available, id], ...] (Google's per-hotel attribute ids)."""
    out = []
    for row in block or []:
        aid = _int(_at(row, 1))
        if aid is None:
            continue
        out.append({"id": aid, "name": AMENITY_IDS.get(aid), "is_available": bool(_at(row, 0))})
    return out


def _vacation_rental(block):
    """[19]: [_, [_, bedrooms, bathrooms, beds, _], _, [[check-in text, check-out text], _, flag], ..., [8] booking sites]"""
    if not isinstance(block, list):
        return None
    sites = []
    for row in _at(block, 8) or []:
        name = _text(_at(row, 0))
        if name:
            sites.append({"name": name, "link": _absolute(_at(row, 4)) if isinstance(_at(row, 4), str) else None,
                          "logo": _image_url(_at(row, 1))})
    times = _at(block, 3, 0) or []

    def clock(label):
        # 'Check-in time: 1300' -> '13:00'
        value = (_text(label) or "").split(":", 1)[-1].strip()
        return f"{value[:-2]}:{value[-2:]}" if value.isdigit() and len(value) in (3, 4) else (value or None)

    return {
        "bedrooms": _int(_at(block, 1, 1)),
        "bathrooms": _int(_at(block, 1, 2)),
        "beds": _int(_at(block, 1, 3)),
        "check_in_time": clock(times[0]) if len(times) > 0 else None,
        "check_out_time": clock(times[1]) if len(times) > 1 else None,
        "booking_sites": sites,
    }


def _attributes(block):
    """[10][0] = [[group, [[label, _, icon, _, label], ...]], ...] ("Crowd": LGBTQ+ friendly)."""
    out = []
    for group in block or []:
        group_name = _text(_at(group, 0))
        for item in _at(group, 1) or []:
            label = _text(_at(item, 0))
            if label:
                out.append({"group": group_name, "name": label})
    return out


def _photo_categories(block):
    return _categories(_at(block, 0))


def parse_hotel_record(rec, currency="USD"):
    """One hotel record (search entry, matched hotel or entity page ds:1[0])
    -> the clean hotel dict. Keys are stable across the three surfaces;
    entity-page-only data (address, phone, website...) is None elsewhere."""
    if not isinstance(rec, list):
        return None
    token = _at(rec, 20) if isinstance(_at(rec, 20), str) else None
    place = _at(rec, 2) if isinstance(_at(rec, 2), list) else []
    primary_type, all_types = _types(_at(place, 31))
    reviews = _reviews_block(_at(rec, 7))
    kind = PROPERTY_KINDS.get(_int(_at(rec, 14)))
    feature_id = _at(rec, 9) if isinstance(_at(rec, 9), str) and FEATURE_ID_RE.match(_at(rec, 9)) else None
    times = _at(place, 17) or []
    areas = [{"name": _text(_at(a, 1)), "knowledge_graph_id": _at(a, 0) if isinstance(_at(a, 0), str) else None}
             for a in (_at(place, 21) or []) if _text(_at(a, 1))]
    description = _at(rec, 11) or []
    paragraphs = [_text(p) for p in (_at(description, 1) or []) if _text(p)]
    bounds = _at(place, 34)
    return {
        "id": token,
        "name": _text(_at(rec, 1)),
        "link": refs.hotel_link(token) if token else None,
        "property_type": kind,
        "primary_type": primary_type,
        "types": all_types,
        "hotel_class": _int(_at(rec, 3, 1)),
        "hotel_class_label": _text(_at(rec, 3, 0)),
        "description": _text(_at(description, 0)),
        "description_paragraphs": paragraphs,
        "rating": reviews["rating"],
        "reviews_count": reviews["reviews_count"],
        "price": _price_block(_at(rec, 6, 2), currency),
        "offers": _offers(_at(rec, 6, 2, 21), (_at(rec, 6, 2, 15) if isinstance(_at(rec, 6, 2, 15), str) else currency)),
        "check_in_time": _text(_at(times, 0)) if times else None,
        "check_out_time": _text(_at(times, 1)) if times else None,
        "location": {
            "latitude": _num(_at(place, 0, 0)),
            "longitude": _num(_at(place, 0, 1)),
            "address": _text(_at(place, 1, 0, 0, 0)),
            "neighborhood": _text(_at(place, 12, 3)),
            "neighborhood_description": _text(_at(place, 12, 4)),
            "areas": areas,
            "country_code": _at(place, 36) if isinstance(_at(place, 36), str) else None,
            "bounds": {"south": _num(_at(bounds, 0, 0)), "west": _num(_at(bounds, 0, 1)),
                       "north": _num(_at(bounds, 1, 0)), "east": _num(_at(bounds, 1, 1))}
            if isinstance(bounds, list) and len(bounds) == 2 else None,
            "maps_link": _at(place, 13, 2) if isinstance(_at(place, 13, 2), str) else None,
            "directions_link": _at(place, 14, 2) if isinstance(_at(place, 14, 2), str) else None,
        },
        "contact": {
            "phone": _text(_at(place, 2, 0)),
            "website": _at(place, 29, 2) if isinstance(_at(place, 29, 2), str) else None,
        },
        "nearby": [n for n in _nearby(_at(place, 19)) if n["name"] != _text(_at(rec, 1))],
        "amenities": _amenity_flags(_at(rec, 10, 8)),
        "attributes": _attributes(_at(rec, 10, 0)),
        "is_eco_certified": _at(rec, 10, 6, 3, 1) is True,
        "reviews": {
            "histogram": reviews["histogram"],
            "topics": reviews["topics"],
            "sources": reviews["sources"],
            "source_ratings": reviews["source_ratings"],
        },
        "images": _images(_at(rec, 5)),
        "thumbnail": _image_url(_at(rec, 12, 0)),
        "photo_categories": _photo_categories(_at(rec, 38)),
        "vacation_rental": _vacation_rental(_at(rec, 19)) if kind == "vacation_rental" else None,
        "ids": {
            "entity_token": token,
            "maps_cid": _at(rec, 25) if isinstance(_at(rec, 25), str) else None,
            "maps_feature_id": feature_id,
            "place_id": _at(rec, 26, 4) if isinstance(_at(rec, 26, 4), str) else None,
        },
    }


# ---- hotels/search --------------------------------------------------------------

def _search_state(payload):
    """The resolved search echoed back: place id / name and the dated stay."""
    for state in _walk_key(payload, "404340221", []):
        for candidate in (state, _at(state, 0)):
            where = _at(candidate, 18)
            if isinstance(where, list) and isinstance(_at(where, 2), str):
                return {"id": _at(where, 2), "name": _text(_at(where, 1))}
    return None


def parse_search(payload, currency="USD"):
    """AtySUc payload -> {results, total_count, has_next, place, is_single_hotel}.
    A place search lists 20 records under "397419284"; a query that names
    one hotel answers that hotel under "441552390" instead (plus nearby
    alternatives under "179305178", not returned here)."""
    records = []
    for sub in _walk_key(payload, "397419284", []):
        if isinstance(sub, list):
            records.extend(r for r in sub if isinstance(r, list))
    single = False
    if not records:
        for block in _walk_key(payload, "441552390", []):
            if isinstance(block, list) and isinstance(_at(block, 1), str):
                records.append(block)
                single = True
                break
    results = [h for h in (parse_hotel_record(r, currency) for r in records) if h and h["name"]]
    total = None
    for meta in _walk_key(payload, "416343588", []):
        if isinstance(meta, list) and _num(_at(meta, 0)) is not None:
            total = _int(_at(meta, 0))
            break
    has_next = False
    for cursor in _walk_key(payload, "469845717", []):
        if isinstance(cursor, list) and isinstance(_at(cursor, 0), str) and _at(cursor, 0):
            has_next = True
            break
    if single:
        total, has_next = len(results), False
    return {"results": results, "total_count": total, "has_next": has_next,
            "place": _search_state(payload), "is_single_hotel": single}


# ---- hotels/details: the amenities list is HTML only ---------------------------

_AMENITY_GROUP_NAME_RE = re.compile(r'<span class="LtjZ2d">([^<]+)</span>')
_AMENITY_LIST_RE = re.compile(r'<ul class="BCbrYd">(.*?)</ul>', re.S)
_AMENITY_ITEM_RE = re.compile(
    r'<li class="IXICF">.*?<span class="LtjZ2d">(?P<name>[^<]+)</span>(?:\s*<span class="AdLXZd[^"]*">(?P<note>[^<]+)</span>)?',
    re.S)
_POPULAR_RE = re.compile(r'<h3[^>]*>Popular amenities</h3>\s*<ul[^>]*>(?P<items>.*?)</ul>', re.S)
_POPULAR_ITEM_RE = re.compile(
    r'<li[^>]*>.*?<span class="LtjZ2d">(?P<name>[^<]+)</span>(?:\s*<span class="AdLXZd[^"]*">(?P<note>[^<]+)</span>)?', re.S)


def parse_amenities(html):
    """The entity page's amenities dialog -> [{group, name, note, is_available}]
    plus the "Popular amenities" strip when the dialog is absent (captured
    2026-10-30, The People Paris Marais; Bellagio 2026-11-02). The dialog is
    a run of <h4>group</h4><ul class="BCbrYd"><li>item…</ul> blocks after
    its ">Amenities</h2>" heading; each group is read from its own block so
    a stray earlier <h4> on the page can never shift the pairing. "No
    pools" style rows are reported with is_available false."""
    html = html or ""
    out, seen = [], set()
    start = html.find(">Amenities</h2>")
    if start >= 0:
        for chunk in re.split(r"<h4\b", html[start:])[1:]:
            head, _, rest = chunk.partition("</h4>")
            group = _AMENITY_GROUP_NAME_RE.search(head)
            items = _AMENITY_LIST_RE.match(rest.lstrip())
            if not group or not items:
                continue
            group_name = html_lib.unescape(group.group(1)).strip()
            for item in _AMENITY_ITEM_RE.finditer(items.group(1)):
                name = html_lib.unescape(item.group("name")).strip()
                note = html_lib.unescape(item.group("note")).strip() if item.group("note") else None
                key = (group_name, name)
                if name and key not in seen:
                    seen.add(key)
                    out.append({"group": group_name, "name": name, "note": note,
                                "is_available": not name.lower().startswith(("no ", "not "))})
    if not out:
        popular = _POPULAR_RE.search(html)
        if popular:
            for item in _POPULAR_ITEM_RE.finditer(popular.group("items")):
                name = html_lib.unescape(item.group("name")).strip()
                note = html_lib.unescape(item.group("note")).strip() if item.group("note") else None
                if name:
                    out.append({"group": "Popular amenities", "name": name, "note": note, "is_available": True})
    return out


def parse_entity(ds1, html=None, currency="USD"):
    """Entity page ds:1 (+ its HTML for the amenity list) -> the hotel record
    with `amenity_groups` filled."""
    record = parse_hotel_record(_at(ds1, 0), currency)
    if record is None:
        return None
    record["amenity_groups"] = parse_amenities(html) if html else []
    return record


# ---- hotels/reviews ----------------------------------------------------------------

def _owner_response(block):
    if not isinstance(block, list):
        return None
    paragraphs = [_html_text(p) for p in (_at(block, 0) or []) if isinstance(p, str) and _html_text(p)]
    if not paragraphs:
        return None
    return {"text": "\n".join(paragraphs), "date_text": _text(_at(block, 1))}


def _review(row):
    body = _at(row, 1)
    if not isinstance(body, list):
        return None
    text = _html_text(_at(body, 3, 0, 0, 3)) or _html_text(_at(body, 3, 0, 0, 1))
    visited = _at(body, 10)
    aspects = []
    for aspect in _at(body, 7) or []:
        aid = _int(_at(aspect, 0))
        score = _num(_at(aspect, 1, 0))
        if aid is not None and score is not None:
            aspects.append({"aspect": REVIEW_ASPECTS.get(aid, f"aspect_{aid}"), "rating": score,
                            "rating_max": _int(_at(aspect, 1, 1))})
    source_link = _at(row, 0, 1)
    return {
        "id": _at(body, 8) if isinstance(_at(body, 8), str) else None,
        "source": _text(_at(row, 0, 0)),
        "source_link": _absolute(source_link) if isinstance(source_link, str) else None,
        "rating": _num(_at(body, 2, 0)),
        "rating_max": _int(_at(body, 2, 1)),
        "text": text,
        "date_text": _text(_at(body, 1)),
        "visited": {"year": _int(_at(visited, 0)), "month": _int(_at(visited, 1))} if isinstance(visited, list) else None,
        "visited_text": _text(_at(body, 9)),
        "aspects": aspects,
        "author": {
            "name": _text(_at(body, 0, 0)),
            "link": _absolute(_at(body, 0, 1)) if isinstance(_at(body, 0, 1), str) else None,
            "avatar": _image_url(_at(body, 0, 2, 0)),
        },
        "owner_response": _owner_response(_at(body, 5)),
    }


def parse_reviews(payload):
    """ocp93e payload -> {reviews, next_token} (captured 2026-10-31)."""
    reviews = [r for r in (_review(row) for row in (_at(payload, 0, 0) or [])) if r]
    token = _at(payload, 0, 5)
    return {"reviews": reviews, "next_token": token if isinstance(token, str) and token else None}


# ---- hotels/photos -----------------------------------------------------------------

def _photo(group):
    url = _at(group, 0)
    if not isinstance(url, str):
        return None
    dims = _at(group, 7, 2, 2)
    author_name = _text(_at(group, 1, 0))
    return {
        "link": _image_url(url),
        "original_link": _original_image(url),
        "width": _int(_at(dims, 0)) if isinstance(dims, list) else _int(_at(group, 4)),
        "height": _int(_at(dims, 1)) if isinstance(dims, list) else _int(_at(group, 5)),
        "uploaded_on": _epoch_iso(_at(group, 9, 0)),
        "author": {
            "name": author_name,
            "link": _absolute(_at(group, 1, 2)) if isinstance(_at(group, 1, 2), str) else None,
            "avatar": _image_url(_at(group, 1, 1)),
        } if author_name else None,
    }


def parse_photos(gallery_payload, categories_payload=None):
    """pSDzMb (+ zM1L7d) payloads -> {photos, categories}."""
    photos = [p for p in (_photo(g) for g in (_at(gallery_payload, 0) or [])) if p]
    rows = _at(categories_payload, 0) or _at(gallery_payload, 1, 4) or []
    return {"photos": photos, "categories": _categories(rows)}


def _categories(rows):
    """[[id, visitor flag, 360 flag, count, [thumb]], ...] -> [{name,
    photos_count, thumbnail}]: the content categories (bedroom, exterior…)
    and the gallery tabs (from_visitors, by_owner, 360_view)."""
    out = []
    for row in rows or []:
        count = _int(_at(row, 3))
        if count is None:
            continue
        cid = _int(_at(row, 0))
        if cid is not None:
            name = PHOTO_CATEGORIES.get(cid)
        elif _at(row, 2) == 1:
            name = "360_view"
        elif _at(row, 1) == 1:
            name = "from_visitors"
        else:
            name = "by_owner"
        out.append({"name": name, "photos_count": count, "thumbnail": _image_url(_at(row, 4, 0))})
    return out


def photos_total(categories):
    """All photos = the three gallery tabs (visitors + owner + 360°)."""
    counts = [c["photos_count"] for c in categories if c["name"] in ("from_visitors", "by_owner", "360_view")]
    return sum(counts) if counts else None


# ---- places/autocomplete -------------------------------------------------------------

def parse_autocomplete(payload):
    """mejVKc payload -> suggestions [{text, highlighted}] (query completions;
    Google's hotel typeahead returns no entity rows for a bare text call)."""
    out = []
    for row in _at(payload, 0) or []:
        text = _text(_at(row, 1))
        if not text:
            continue
        parts = [_text(_at(p, 0)) for p in (_at(row, 5) or []) if _at(p, 1) is True and _text(_at(p, 0))]
        out.append({"text": text, "completion": " ".join(parts).strip() or None})
    return out


# ---- places/price-trends -------------------------------------------------------------

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def parse_price_trends(payload, currency="USD"):
    """axSywf payload -> {months: [...], description}. Each month row is
    [[high temp, low temp, _, _, rainy days, _], [crowd 1-5], [price level
    1-5, symbol, low display, high display]], January first."""
    months = []
    for index, row in enumerate(_at(payload, 1, 1) or []):
        if not isinstance(row, list):
            continue
        weather, crowd, price = _at(row, 0), _at(row, 1), _at(row, 2)
        low_display, high_display = _text(_at(price, 2)), _text(_at(price, 3))
        months.append({
            "month": MONTHS[index % 12],
            "month_number": index % 12 + 1,
            "price_level": _int(_at(price, 0)),
            "price_from": {"amount": _amount_from_display(low_display), "currency": currency, "display": low_display}
            if low_display else None,
            "price_to": {"amount": _amount_from_display(high_display), "currency": currency, "display": high_display}
            if high_display else None,
            "crowd_level": _int(_at(crowd, 0)),
            "high_temperature": _int(_at(weather, 0)),
            "low_temperature": _int(_at(weather, 1)),
            "rainy_days": _int(_at(weather, 4)),
        })
    return {"months": months, "description": _text(_at(payload, 1, 3))}


# Per-hotel attribute ids (record [10][8]). Derived 2026-11-01 by aligning
# the search card's own amenity strip ("Breakfast ($), Free Wi-Fi, …") with
# the record's true flags over 139 hotels in 12 cities (139 matched, 49 with
# equal counts; each row below won its id by a clear majority). Ids seen
# without a majority name (5, 7, 9, 10, 20, 21, 22, 24, 26, 30, 31, 150,
# 166, 261, 262) are reported with name null.
AMENITY_IDS = {
    1: "Airport shuttle", 2: "Air conditioning", 4: "Bar", 6: "Free breakfast", 8: "Fitness center",
    11: "Kid-friendly", 12: "Kitchen in rooms", 14: "Kitchen in some rooms", 15: "Parking",
    16: "Free parking", 17: "Paid parking", 18: "Pet-friendly", 19: "Pool", 23: "Restaurant",
    25: "Smoke-free property", 27: "Accessible", 28: "Wi-Fi", 29: "Free Wi-Fi", 54: "Breakfast",
    165: "Paid breakfast",
}
