"""Cache TTL per /google-hotels/* endpoint (cache.py, keyed on the validated
params, so a stay's dates / occupancy / currency are part of every key).
Prices move by the hour on Google Hotels, static hotel facts by the month.
"""
from datetime import timedelta

# A results page for one place + stay + filters: prices are live quotes.
SEARCH_CACHE = timedelta(hours=1)
# One hotel's page record (facts + the headline price for the stay): the
# price part is what expires, the facts would last for weeks.
DETAILS_CACHE = timedelta(hours=1)
# The vendor rate ladder for one stay: the most volatile surface.
PRICES_CACHE = timedelta(minutes=30)
# Reviews arrive a few a day on busy hotels; a page is keyed on its sort
# and continuation token.
REVIEWS_CACHE = timedelta(hours=6)
# Galleries change when the owner or guests upload; daily is plenty.
PHOTOS_CACHE = timedelta(hours=24)
# Typeahead suggestions are query-frequency driven and move slowly.
AUTOCOMPLETE_CACHE = timedelta(hours=24)
# Seasonal price / weather / crowd bands for a destination: monthly data.
PRICE_TRENDS_CACHE = timedelta(hours=24)
