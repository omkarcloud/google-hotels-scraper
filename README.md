# 🏨 Google Hotels Scraper

Google Hotels Scraper is a **free and open-source** scraper that gets you **unlimited** live Google Hotels data for free.

## ✨ What Can I Get?

- 🏨 **Full details on any hotel on Google** — star class, rating, address, phone, website, the full amenity list, nearby places & review topics
- 💰 **Live rates from up to 24 booking sites per hotel** — Booking.com, Expedia, Hotels.com, the hotel's own site & more, with taxes, resort fees and booking links
- 🔍 **Search up to 15,000 hotels per city** — live nightly prices, star class, rating, amenity & price filters, vacation rentals too
- ⭐ **Every review & photo** — guest reviews with owner replies, and full-size photo galleries (470,000+ for the Bellagio alone)

## 🎰 Example: A Full Google Hotels Listing

```json
{
  "id": "ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE",
  "name": "Bellagio Hotel & Casino",
  "link": "https://www.google.com/travel/hotels/entity/ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE",
  "hotel_class": 5,
  "description": "Luxe quarters in a ritzy casino resort offering outdoor pools, a spa & posh dining, plus live shows.",
  "rating": 4.7,
  "reviews_count": 144377,
  "price": {
    "currency": "USD",
    "nightly": { "amount": 203.55, "currency": "USD", "display": "$204" },
    "base_price": 148.55,
    "taxes": 26.47,
    "fees": 55.0,
    "total_with_taxes_and_fees": 230.02,
    "deal": "35% less than usual"
  },
  "location": {
    "latitude": 36.1129455,
    "longitude": -115.17650669999999,
    "address": "3600 S Las Vegas Blvd, Las Vegas, NV 89109",
    "neighborhood": "Las Vegas Strip"
  },
  "contact": { "phone": "(888) 987-6667", "website": "https://bellagio.mgmresorts.com/en.html?ecid=GMB_BE_HO" },
  "nearby": [
    { "name": "The Venetian Las Vegas", "kind": "top_sight", "travel_times": [{ "mode": "driving", "duration": "7 min" }] }
  ],
  "amenity_groups": [
    { "group": "Internet", "name": "Wi-Fi", "note": "extra charge", "is_available": true }
  ],
  "reviews": {
    "histogram": [{ "stars": 5, "percent": 79, "count": 111034 }],
    "topics": [{ "name": "Nightlife", "mentions": 9582, "positive": 7684, "negative": 1098, "sentiment": 0.6 }],
    "source_ratings": [{ "name": "Tripadvisor", "rating": 4.0, "rating_max": 5, "reviews_count": 15992 }]
  },
  "offers_count": 22
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Google Hotels Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/google-hotels-scraper
cd google-hotels-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/hotels/details?hotel=ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE"
```

```json
{
  "id": "ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE",
  "name": "Bellagio Hotel & Casino",
  "link": "https://www.google.com/travel/hotels/entity/ChYIhJvEzt34sfmCARoJL20vMDMzYnhzEAE",
  "hotel_class": 5,
  "rating": 4.7,
  "reviews_count": 144377,
  "price": {
    "currency": "USD",
    "nightly": { "amount": 203.55, "currency": "USD", "display": "$204" },
    "taxes": 26.47,
    "fees": 55.0,
    "total_with_taxes_and_fees": 230.02,
    "deal": "35% less than usual"
  },
  "location": { "address": "3600 S Las Vegas Blvd, Las Vegas, NV 89109", "neighborhood": "Las Vegas Strip" },
  "contact": { "phone": "(888) 987-6667", "website": "https://bellagio.mgmresorts.com/en.html?ecid=GMB_BE_HO" },
  "offers_count": 22
}
```

All 7 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

7 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Hotel Details | `/hotels/details` | Everything about one hotel: amenities, nearby places, reviews summary, live price |
| Hotel Prices | `/hotels/prices` | Every booking site's live rate, taxes, fees and booking link |
| Search Hotels | `/hotels/search` | 20 hotels per page with live prices; filter by price, stars, rating, amenities |
| Hotel Reviews | `/hotels/reviews` | Full review text, scores and owner replies, up to 50 per call |
| Hotel Photos | `/hotels/photos` | Full-size photos with uploader, date and counts per category |
| Autocomplete | `/places/autocomplete` | The hotel searches travelers actually type on Google |
| Price Trends | `/places/price-trends` | Month-by-month price range, crowds and weather for any destination |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-google-hotels-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-google-hotels-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-google-hotels-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/hotels/search",
    params={"query": "hotels in Las Vegas", "hotel_class": "4,5", "sort": "lowest_price"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Google Hotels Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/google-hotels-scraper-github-whatsapp)

[![Ask Us by Email about Google Hotels Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Google%20Hotels%20Scraper%20API&body=I%20need%20help%20using%20the%20Google%20Hotels%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Agoda Scraper**](https://github.com/omkarcloud/agoda-scraper) — Agoda hotels: live prices, every room & rate plan, guest scores & reviews
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations
- [**Hotels Com Scraper**](https://github.com/omkarcloud/hotels-com-scraper) — Hotels.com hotels: live prices, every room & rate, reviews and daily price calendars

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/google-hotels-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/google-hotels-scraper)
