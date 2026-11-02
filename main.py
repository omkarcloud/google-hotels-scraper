"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Params go through the same schemas the API uses, so defaults
are filled in (check-in tomorrow, one night, 2 adults, USD) and a hotel ID or
any Google Hotels link both work.
"""
import json
import os

from google_hotels import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def run(schema_cls, fn, **params):
    return fn(**schema_cls().load(params))


if __name__ == "__main__":
    # a hotel ID or any Google Hotels link — the whole hotel page
    save("hotel_bellagio.json",
         run(schemas.HotelSchema, api.hotel_details, hotel="ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE"))

    # every booking site's live rate for the stay
    save("prices_bellagio.json",
         run(schemas.HotelSchema, api.hotel_prices, hotel="ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE"))

    # 20 hotels per page with live prices
    save("search_las_vegas.json",
         run(schemas.HotelsSearchSchema, api.hotels_search, query="hotels in Las Vegas"))
