"""The one network helper the google_hotels module needs: the
Accept-Language its sessions send. Requests go out direct from your own
connection (or your GOOGLE_HOTELS_PROXY), so every session announces the
plain English list a desktop Chrome sends. Names and review text follow the
`language` param, not this header."""

ACCEPT_LANGUAGE = "en-US,en;q=0.9"


def site_accept_language(site=None):
    return ACCEPT_LANGUAGE


def accept_language(proxy=None, country=None):
    return ACCEPT_LANGUAGE
