"""Configuration for the Google Hotels Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                  port the API listens on (default 8000)
    GOOGLE_HOTELS_PROXY   proxy URL for every request, e.g.
                          http://user:pass@host:port (default: none —
                          direct). Google Hotels answers home, office and
                          cloud server IPs alike, so you very likely don't
                          need this. Set it only if Google starts showing its
                          "unusual traffic" page at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# How long a blocked thread stays on the fallback proxy before going back
# to the main one (seconds). Only matters when GOOGLE_HOTELS_PROXY is set.
GOOGLE_HOTELS_DIRECT_COOLDOWN = 600

GOOGLE_HOTELS_PROXY = os.environ.get("GOOGLE_HOTELS_PROXY") or None
GOOGLE_HOTELS_EXIT = "proxy" if GOOGLE_HOTELS_PROXY else "direct"


def google_hotels_proxy():
    """The proxy for one curl session (None = direct)."""
    return os.environ.get("GOOGLE_HOTELS_PROXY") or None


def google_hotels_fallback_proxy():
    """Where a blocked session moves for the cooldown: the same proxy (a
    rotating proxy hands out a fresh IP per connection), or None = just
    reconnect."""
    return os.environ.get("GOOGLE_HOTELS_PROXY") or None
