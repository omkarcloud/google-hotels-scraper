"""Google Hotels transport: plain curl_cffi with chrome TLS, no browser, no
cookies beyond the EU consent skip, no BotGuard (unlike Google Flights, the
TravelFrontendUi hotel RPCs take a bare `f.req`). Egress: the pod's own IP
(config.GOOGLE_HOTELS_EXIT, probed from the patchright pod 2026-10-31: every
surface 200 direct, datacenter and residential alike); a 403 / 429 /
captcha moves the thread to a datacenter exit for
config.GOOGLE_HOTELS_DIRECT_COOLDOWN seconds, and every retryable failure
drops the session so the retry rides a fresh connection.

Upstream surfaces (validated 2026-10-30/31, scratchpad capture*/):

  RPC   POST /_/TravelFrontendUi/data/batchexecute?rpcids=<id>&source-path=
        %2Ftravel%2Fsearch&hl&gl&rt=c   form f.req=[[["<id>","<json>",null,"generic"]]]
          AtySUc  hotel / vacation-rental search (20 records a page, place
                  resolved from the query text, filters + sort + cursor)
          ocp93e  reviews (sort, page size <= 50, continuation token)
          pSDzMb  photo gallery (15 groups, ~440 image URLs), zM1L7d the
                  category counts
          mejVKc  query autocomplete
          axSywf  "When to visit" month bands (price level, crowd, weather)
        rt=c chunked replies: )]}' then length-prefixed JSON lines of
        envelopes ["wrb.fr", rpcid, "<payload json>"] or an error
        ["wrb.fr", null, null, null, null, [code, null, [details]]].
  PAGE  GET /travel/hotels/entity/<token>[/prices]?hl&gl&ts=<proto>  server
        rendered; the data sits in AF_initDataCallback({key: 'ds:1', …}).
        An unknown token answers HTTP 200 with an EMPTY <title> (a real
        hotel titles "<name> - Google hotels"), mapped to NotFound here.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  GoogleHotelsUpstreamError  transport failure / 5xx / unparseable   — retryable
  GoogleHotelsBlocked        403 / 429 / captcha (/sorry/) page       — retryable on the fallback exit
  GoogleHotelsBadRequest     RPC error code 3 (INVALID_ARGUMENT)      — never retried
  GoogleHotelsNotFound       unknown entity token                     — never retried
"""
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlencode

# Allow direct execution (python google_hotels/fetch.py): flat imports
# resolve like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from google_hotels.refs import SITE

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 45      # entity pages are ~2.7 MB
RPC_TIMEOUT = 40
BATCH_PATH = "/_/TravelFrontendUi/data/batchexecute"
SOURCE_PATH = "/travel/search"

RPC_SEARCH = "AtySUc"
RPC_REVIEWS = "ocp93e"
RPC_PHOTOS = "pSDzMb"
RPC_PHOTO_CATEGORIES = "zM1L7d"
RPC_AUTOCOMPLETE = "mejVKc"
RPC_PRICE_TRENDS = "axSywf"

# The EU consent interstitial skip (the same two cookies the Google Flights
# module sends); harmless elsewhere.
CONSENT_COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiA_LyaBg"}

RPC_HEADERS = {
    "accept": "*/*",
    "accept-language": egress.site_accept_language("google-hotels"),
    "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    "origin": SITE,
    "referer": SITE + SOURCE_PATH,
    "x-same-domain": "1",
}
PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": egress.site_accept_language("google-hotels"),
    "upgrade-insecure-requests": "1",
}

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_BLOCK_MARKERS = ("unusual traffic", "/sorry/", "recaptcha", "captcha-form")


# ---- the Travel frontend wire format (same as Google Flights' TravelFrontendUi) ----

_AF_RE = re.compile(r"AF_initDataCallback\(\{key: '(ds:\d+)', hash: '[^']*', data:(.*?), sideChannel: \{\}\}\);", re.S)


def decode_chunks(text):
    """rt=c body -> (payloads, errors). payloads: decoded wrb.fr payloads in
    order; errors: [(code, has_details)] from error envelopes, plus
    ('http', status, code) from "er" envelopes."""
    payloads, errors = [], []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("[["):
            continue
        try:
            envelopes = json.loads(line)
        except ValueError:
            continue
        for env in envelopes:
            if not isinstance(env, list) or not env:
                continue
            if env[0] == "wrb.fr":
                raw = env[2] if len(env) > 2 else None
                if isinstance(raw, str):
                    try:
                        payloads.append(json.loads(raw))
                    except ValueError:
                        pass
                elif len(env) > 5 and isinstance(env[5], list) and env[5]:
                    errors.append((env[5][0], len(env[5]) > 2 and bool(env[5][2])))
            elif env[0] == "er":
                errors.append(("http", env[5] if len(env) > 5 else None, env[9] if len(env) > 9 else None))
    return payloads, errors


def af_blobs(html):
    """{'ds:1': data, ...} from a page's AF_initDataCallback blocks."""
    out = {}
    for key, raw in _AF_RE.findall(html or ""):
        try:
            out[key] = json.loads(raw)
        except ValueError:
            continue
    return out


class GoogleHotelsUpstreamError(UpstreamError):
    """Transport failure, 5xx, empty or unparseable answer — retryable."""


class GoogleHotelsBlocked(GoogleHotelsUpstreamError, Blocked):
    """403 / 429 / captcha — retried on the fallback exit."""


class GoogleHotelsBadRequest(BadRequest):
    """Google rejected the request parameters (RPC code 3) — never retried."""


class GoogleHotelsNotFound(NotFound):
    """No such hotel — never retried."""


# ---- sessions ------------------------------------------------------------------

# One curl session per cheroot worker thread (a curl handle must not be
# shared across threads); its Accept-Language is the exit's.
_local = threading.local()


def _new_state(proxy, fallback_until=None):
    from curl_cffi import requests as curl_requests
    sess = curl_requests.Session(impersonate=IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    language = egress.accept_language(proxy)
    return {
        "session": sess,
        "proxy": proxy,
        "fallback_until": fallback_until,
        "rpc_headers": {**RPC_HEADERS, "accept-language": language},
        "page_headers": {**PAGE_HEADERS, "accept-language": language},
    }


def _state():
    state = getattr(_local, "state", None)
    now = time.monotonic()
    if state is not None and state["fallback_until"] and now > state["fallback_until"]:
        _drop_session()
        state = None
    if state is None:
        state = _local.state = _new_state(config.google_hotels_proxy())
    return state


def _drop_session():
    """Close the thread's session so a poisoned keep-alive connection dies."""
    state = getattr(_local, "state", None)
    _local.state = None
    if state is not None:
        try:
            state["session"].close()
        except Exception:
            pass


def _fallback_session():
    """After a block: move this thread to the fallback exit for the cooldown
    (a fresh sticky port each time), or just reconnect when there is none."""
    proxy = config.google_hotels_fallback_proxy()
    _drop_session()
    if proxy:
        _local.state = _new_state(proxy, time.monotonic() + config.GOOGLE_HOTELS_DIRECT_COOLDOWN)


def _retrying(fn, label):
    """Run fn() under the shared retry policy: Blocked -> fallback exit,
    other UpstreamErrors -> fresh session; BadRequest / NotFound surface
    immediately."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except GoogleHotelsBlocked as e:
            last = e
            _fallback_session()
        except GoogleHotelsUpstreamError as e:
            last = e
            _drop_session()
        print(f"google-hotels: {label} attempt {attempt}/{config.MAX_RETRIES} failed: {last}")
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _classify(resp, label):
    """Map an HTTP response to the error taxonomy; return the body text."""
    if resp.status_code == 404:
        raise GoogleHotelsNotFound(f"{label} not found")
    if resp.status_code == 400:
        raise GoogleHotelsBadRequest(f"Google rejected {label}")
    if resp.status_code in (401, 403, 429):
        raise GoogleHotelsBlocked(f"HTTP {resp.status_code} for {label}")
    if resp.status_code != 200:
        raise GoogleHotelsUpstreamError(f"HTTP {resp.status_code} for {label}")
    text = resp.text
    if "/sorry/" in str(resp.url) or any(m in text[:20000] for m in _BLOCK_MARKERS[:1]):
        raise GoogleHotelsBlocked(f"captcha page for {label}")
    return text


def locale_query(language=None, country=None):
    return {"hl": language or "en", "gl": (country or "US").lower()}


# ---- RPCs ------------------------------------------------------------------------

def _raise_rpc_errors(errors, rpcid):
    """batchexecute error envelopes -> taxonomy (gRPC canonical codes)."""
    for err in errors:
        if err[0] == "http":
            status = err[1]
            if status in (401, 403, 429):
                raise GoogleHotelsBlocked(f"{rpcid}: HTTP {status}")
            raise GoogleHotelsUpstreamError(f"{rpcid}: HTTP {status}")
        code = err[0]
        if code == 3:
            raise GoogleHotelsBadRequest(f"Google rejected the {rpcid} parameters")
        if code == 5:
            raise GoogleHotelsNotFound(f"{rpcid}: not found")
        if code in (7, 8, 16):
            raise GoogleHotelsBlocked(f"{rpcid}: error {code}")
        raise GoogleHotelsUpstreamError(f"{rpcid}: error {code}")
    raise GoogleHotelsUpstreamError(f"{rpcid}: empty response")


def rpc(rpcid, inner, language=None, country=None):
    """One batchexecute RPC -> its decoded payload (a nested list)."""
    freq = json.dumps([[[rpcid, json.dumps(inner, separators=(",", ":"), ensure_ascii=False), None, "generic"]]],
                      separators=(",", ":"), ensure_ascii=False)
    query = {"rpcids": rpcid, "source-path": SOURCE_PATH, **locale_query(language, country), "rt": "c"}
    url = f"{SITE}{BATCH_PATH}?{urlencode(query)}"

    def once():
        state = _state()
        try:
            resp = state["session"].post(url, data={"f.req": freq}, headers=state["rpc_headers"],
                                         timeout=RPC_TIMEOUT)
        except Exception as e:
            raise GoogleHotelsUpstreamError(f"{rpcid}: request failed: {type(e).__name__}: {e}")
        text = _classify(resp, rpcid)
        payloads, errors = decode_chunks(text)
        if payloads and isinstance(payloads[0], list):
            return payloads[0]
        _raise_rpc_errors(errors, rpcid)
    return _retrying(once, rpcid)


# ---- server-rendered entity pages ------------------------------------------------

def _page_title(text):
    match = _TITLE_RE.search(text or "")
    return (match.group(1).strip() if match else "")


def entity_page(token, subpage=None, ts=None, language=None, country=None):
    """GET /travel/hotels/entity/<token>[/<subpage>] -> (html, ds:1 data
    blob). The blob is the whole hotel record (facts, vendor ladder, reviews
    summary); the HTML is kept for the amenities dialog, which is rendered
    only. `ts` is the stay / currency protobuf (refs.ts_param)."""
    path = f"/travel/hotels/entity/{token}" + (f"/{subpage}" if subpage else "")
    query = locale_query(language, country)
    if ts:
        query["ts"] = ts
    url = f"{SITE}{path}?{urlencode(query)}"
    label = f"hotel {token}"

    def once():
        state = _state()
        try:
            resp = state["session"].get(url, headers=state["page_headers"], cookies=CONSENT_COOKIES,
                                        timeout=PAGE_TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise GoogleHotelsUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
        text = _classify(resp, label)
        blobs = af_blobs(text)
        if not blobs:
            if "consent.google" in str(resp.url):
                raise GoogleHotelsBlocked(f"{label}: consent interstitial")
            raise GoogleHotelsUpstreamError(f"{label}: unexpected page (no data blocks)")
        if not _page_title(text) or "ds:1" not in blobs:
            # Google answers an unknown token with a 200 shell whose <title> is empty.
            raise GoogleHotelsNotFound(f"no Google Hotels entity {token}")
        return text, blobs["ds:1"]
    return _retrying(once, label)
