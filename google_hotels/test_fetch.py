"""Offline tests for the Google Hotels exit tiers (google_hotels/fetch.py):
the pod's own IP, the gateway exit for the cooldown after a block, a
datacenter exit as the last retry of a call the gateway also failed
(2026-11-11). No network: egress.new_session is replaced by scripted sessions.

    python -m pytest google_hotels/test_fetch.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_hotels import fetch as F  # noqa: E402
from scraper_utils.testing import hosted_only

DC = "http://user:pw@dc.example:823"
OK = ')]}\'\n\n30\n[["wrb.fr","mejVKc","[1,2]",null,null,null,"generic"]]\n'


class Resp:
    def __init__(self, status=200, text=OK, url="https://www.google.com/_/TravelFrontendUi/data/batchexecute"):
        self.status_code, self.text, self.url = status, text, url


class Sess:
    def __init__(self, exit_, responses):
        self.exit, self.responses, self.closed = exit_, responses, False

    def post(self, url, **kwargs):
        return self.responses.pop(0)

    def close(self):
        self.closed = True


@pytest.fixture
def tiers(monkeypatch):
    """`tiers.script({exit: [response, ...]})`; `tiers.built` lists the exit
    of every session built."""
    monkeypatch.setattr(F.config, "GOOGLE_HOTELS_EXIT", "direct")
    monkeypatch.setattr(F.config, "GOOGLE_HOTELS_FALLBACK_EXIT", "gateway")
    monkeypatch.setattr(F.config, "GOOGLE_HOTELS_DIRECT_COOLDOWN", 600)
    monkeypatch.setattr(F.config, "datacenter_proxy", lambda *a, **k: DC)
    monkeypatch.setattr(F.config, "MAX_RETRIES", 3)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    scripted, built = {}, []

    def new_session(exit_, impersonate="chrome", **kw):
        built.append(exit_)
        return Sess(exit_, scripted.setdefault(exit_, []))

    monkeypatch.setattr(F.egress, "new_session", new_session)
    F._local.__dict__.clear()
    F.script = lambda by_exit: scripted.update(by_exit)
    F.built = built
    yield F
    F._local.__dict__.clear()


@hosted_only
def test_knobs_name_the_gateway_as_the_fallback_and_a_datacenter_exit_as_the_last_retry(tiers):
    assert F.config.google_hotels_proxy() is None
    assert F.config.google_hotels_fallback_proxy() == "gateway"
    assert F.config.google_hotels_fallback_proxy(last=True) == DC


@hosted_only
def test_a_block_on_the_own_ip_moves_the_thread_to_the_gateway_for_the_cooldown(tiers):
    F.script({None: [Resp(429)], "gateway": [Resp(), Resp()]})
    assert F.rpc("mejVKc", ["x"]) == [1, 2]
    assert F.built == [None, "gateway"]
    assert F.rpc("mejVKc", ["y"]) == [1, 2]             # the next call: still the gateway session
    assert F.built == [None, "gateway"] and F._local.state["fallback_until"]


@hosted_only
def test_a_gateway_failure_degrades_to_a_datacenter_exit_for_the_rest_of_the_cooldown(tiers):
    F.script({None: [Resp(403)], "gateway": [Resp(200, "our systems have detected unusual traffic")], DC: [Resp(), Resp()]})
    assert F.rpc("mejVKc", ["x"]) == [1, 2]
    assert F.built == [None, "gateway", DC]
    state = F._local.state
    assert state["proxy"] == DC and state["fallback_until"] and not state["once"]
    assert F.rpc("mejVKc", ["y"]) == [1, 2] and F.built == [None, "gateway", DC]     # as before the gateway


@hosted_only
def test_the_gateway_as_the_main_exit_gets_one_datacenter_retry_per_call(tiers, monkeypatch):
    monkeypatch.setattr(F.config, "GOOGLE_HOTELS_EXIT", "gateway")
    monkeypatch.setattr(F.config, "GOOGLE_HOTELS_FALLBACK_EXIT", None)
    F.script({"gateway": [Resp(502), Resp(502), Resp()], DC: [Resp()]})
    assert F.rpc("mejVKc", ["x"]) == [1, 2]
    assert F.built == ["gateway", "gateway", DC] and F._local.state is None     # the datacenter session ended with the call
    assert F.rpc("mejVKc", ["y"]) == [1, 2] and F.built[-1] == "gateway"


@hosted_only
def test_a_call_every_tier_fails_ends_after_three_attempts(tiers):
    F.script({None: [Resp(429)], "gateway": [Resp(429)], DC: [Resp(429)]})
    with pytest.raises(F.GoogleHotelsBlocked):
        F.rpc("mejVKc", ["x"])
    assert F.built[:3] == [None, "gateway", DC]


@hosted_only
def test_with_a_datacenter_fallback_nothing_changes(tiers, monkeypatch):
    monkeypatch.setattr(F.config, "GOOGLE_HOTELS_FALLBACK_EXIT", "datacenter")
    F.script({None: [Resp(429)], DC: [Resp(429), Resp()]})
    assert F.rpc("mejVKc", ["x"]) == [1, 2]
    assert F.built == [None, DC, DC] and not F._local.state["once"]


@hosted_only
def test_a_gateway_session_carries_the_consent_cookies_in_a_cookie_header(tiers):
    on_gateway, direct = F._new_state("gateway"), F._new_state(None)
    assert on_gateway["page_cookies"] is None           # cookies= would be bound to the gateway's own host
    assert on_gateway["page_headers"]["cookie"] == "; ".join(f"{k}={v}" for k, v in F.CONSENT_COOKIES.items())
    assert direct["page_cookies"] == F.CONSENT_COOKIES and "cookie" not in direct["page_headers"]
