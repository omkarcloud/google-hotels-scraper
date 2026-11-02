"""Marshmallow request schemas for every /google-hotels/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
url / id pair):

    hotel          a Google Hotels entity token (ChkInMKgie3-lY1lGg0vZy8xMXJ0X3M0dno0EAE)
                   OR any Google Hotels entity link
    query          free text: a city / area / landmark ("hotels in paris",
                   "near Times Square") or a hotel name
    children_ages  comma list of ages 0-17, one per child

Every stay-priced endpoint shares StaySchema: check_in (default tomorrow),
check_out (default one night), adults, children_ages, currency, language
(Google's hl) and country (Google's gl, the market the prices are quoted
for). Choice tables are literals in google_hotels/refs.py.
"""
from datetime import date, timedelta

from marshmallow import ValidationError, fields, post_load, validate, validates_schema

from google_hotels import refs
from schema_fields import (BaseSchema, ChoiceField, CommaListField, CountryCodeField, CurrencyField, DateField,
                           LanguageCodeField, LimitField, PageField, PositiveInt, Price, QueryField, RefField,
                           StrippedString)

MAX_ADULTS = 8
MAX_NIGHTS = 30
SORTS = list(refs.SORTS)
REVIEW_SORTS = list(refs.REVIEW_SORTS)
PROPERTY_TYPES = list(refs.PROPERTY_TYPES)
AMENITIES = list(refs.AMENITY_FILTERS)


class HotelRefField(RefField):
    resolver = staticmethod(refs.resolve_hotel)


class ChildrenAgesField(RefField):
    resolver = staticmethod(refs.children_ages_ref)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


# ---- shared blocks ---------------------------------------------------------------

class LocaleSchema(BaseSchema):
    currency = CurrencyField(load_default="USD", metadata={
        "description": "ISO 4217 code every price is quoted in (USD, EUR, INR, ...)"})
    language = LanguageCodeField(load_default="en", metadata={
        "description": "language of names, descriptions and review text (en, fr, de, ja, ...)"})
    country = CountryCodeField(load_default="US", metadata={
        "description": "2-letter market the search is made from (US, GB, IN, ...): sets the booking sites and taxes shown"})


class StaySchema(LocaleSchema):
    check_in = DateField(bound="future", default_days_ahead=1, metadata={
        "description": "check-in date YYYY-MM-DD, today or later (default tomorrow)"})
    check_out = DateField(bound="future", metadata={
        "description": "check-out date YYYY-MM-DD, after check_in (default one night)"})
    adults = PositiveInt(load_default=2, max_value=MAX_ADULTS, metadata={
        "description": "adults in the room, 1-8 (default 2)"})
    children_ages = ChildrenAgesField(metadata={
        "description": "ages of the children in the room, comma separated (e.g. 5,12), 0-17 each"})

    @validates_schema
    def _nights(self, data, **kwargs):
        check_in, check_out = data.get("check_in"), data.get("check_out")
        if check_in and check_out:
            nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
            if nights < 1:
                raise ValidationError("Must be after check_in.", "check_out")
            if nights > MAX_NIGHTS:
                raise ValidationError(f"At most {MAX_NIGHTS} nights.", "check_out")

    @post_load
    def _default_check_out(self, data, **kwargs):
        if data.get("check_in") and not data.get("check_out"):
            data["check_out"] = (date.fromisoformat(data["check_in"]) + timedelta(days=1)).isoformat()
        return data


# ---- hotels/search -----------------------------------------------------------------

class HotelsSearchSchema(StaySchema):
    query = QueryField(metadata={
        "description": "where to stay: a city, area or landmark (\"hotels in paris\", \"near Times Square\") or a hotel name"})
    sort = ChoiceField(SORTS, load_default="relevance", metadata={
        "description": "relevance (default), lowest_price, highest_rating or most_reviewed"})
    min_price = Price(metadata={"description": "lowest nightly price to keep, in `currency`"})
    max_price = Price(metadata={"description": "highest nightly price to keep, in `currency`"})
    hotel_class = CommaListField(allowed=refs.HOTEL_CLASSES, max_items=4, metadata={
        "description": "star classes to keep, comma separated: 2, 3, 4, 5 (e.g. 4,5)"})
    min_rating = ChoiceField(dict(refs.GUEST_RATINGS), metadata={
        "description": "minimum guest rating: 3.5, 4 or 4.5 (Google's own steps)"})
    amenities = CommaListField(value_map=refs.AMENITY_FILTERS, max_items=10, metadata={
        "description": "amenities every result must have, comma separated: " + ", ".join(AMENITIES)})
    property_type = ChoiceField(dict(refs.PROPERTY_TYPES), load_default=refs.PROPERTY_TYPES["hotel"], metadata={
        "description": "hotel (default) or vacation_rental"})
    page = PageField(max_page=750, metadata={   # refs.MAX_PAGE: Google's 15,000-result cap / 20 per page
        "description": "results page, 20 hotels each (Google lists at most 15,000)"})

    @validates_schema
    def _price_band(self, data, **kwargs):
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            raise ValidationError("Must not be below min_price.", "max_price")


# ---- hotels/details, hotels/prices -----------------------------------------------------

class HotelSchema(StaySchema):
    hotel = HotelRefField(metadata={
        "description": "Google Hotels entity token (ChkI...EAE) or an entity link (https://www.google.com/travel/hotels/entity/<token>)"})


# ---- hotels/reviews ------------------------------------------------------------------

class ReviewsSchema(BaseSchema):
    hotel = HotelRefField(metadata={
        "description": "Google Hotels entity token (ChkI...EAE) or an entity link"})
    sort = ChoiceField(dict(refs.REVIEW_SORTS), load_default=refs.REVIEW_SORTS["most_helpful"], metadata={
        "description": "most_helpful (default), most_recent, highest_rating or lowest_rating"})
    limit = LimitField(default=10, max_size=refs.REVIEWS_PAGE_MAX, metadata={
        "description": "reviews per call, 1-50 (default 10)"})
    next_token = StrippedString(required=False, load_default=None, validate=validate.Length(max=512), metadata={
        "description": "continuation token from the previous reply's `next_token` (same hotel, sort and limit)"})
    language = LanguageCodeField(load_default="en", metadata={
        "description": "language of the review text Google shows (translations follow it)"})
    country = CountryCodeField(load_default="US", metadata={"description": "2-letter market (US, GB, IN, ...)"})


# ---- hotels/photos ---------------------------------------------------------------------

class PhotosSchema(BaseSchema):
    hotel = HotelRefField(metadata={
        "description": "Google Hotels entity token (ChkI...EAE) or an entity link"})
    language = LanguageCodeField(load_default="en", metadata={"description": "language of the category labels"})
    country = CountryCodeField(load_default="US", metadata={"description": "2-letter market (US, GB, IN, ...)"})


# ---- places/autocomplete -------------------------------------------------------------

class AutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={
        "description": "what the traveller has typed so far (\"hotels in lis\")"})
    language = LanguageCodeField(load_default="en", metadata={"description": "language of the suggestions"})
    country = CountryCodeField(load_default="US", metadata={"description": "2-letter market the suggestions are ranked for"})


# ---- places/price-trends -------------------------------------------------------------

class PriceTrendsSchema(LocaleSchema):
    query = QueryField(metadata={
        "description": "the destination (\"hotels in paris\", \"Bali\")"})
