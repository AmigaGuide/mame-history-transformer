from unittest.mock import Mock

import requests

from mht.provenance import fetch


SUPPORT_HTML = """
<a href="/download/?file=pS_SupportFiles_287.zip&amp;tipo=support_pack">
    Support 0.287
</a>
"""

CATVER_HTML = """
<a href="/download/?file=pS_CatVer_289.zip&amp;tipo=catver">
    CatVer 0.289
</a>
"""


def test_probe_snaps_resolves_historical_release(monkeypatch):
    def fake_get(url, **kwargs):
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = (
            SUPPORT_HTML if url == fetch.SUPPORT_URL
            else CATVER_HTML
        )
        return response

    monkeypatch.setattr(fetch.requests, "get", fake_get)

    source = fetch.probe_snaps("0287")

    assert source is not None
    assert source.package_type == "supportfiles"
    assert source.filename == "pS_SupportFiles_287.zip"


def test_probe_snaps_does_not_substitute_newer_release(monkeypatch):
    def fake_get(url, **kwargs):
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = CATVER_HTML
        return response

    monkeypatch.setattr(fetch.requests, "get", fake_get)

    assert fetch.probe_snaps("0287") is None


def test_probe_snaps_handles_failed_page_request(monkeypatch):
    def fake_get(url, **kwargs):
        if url == fetch.CATVER_URL:
            raise requests.ConnectionError("Connection failed")

        response = Mock()
        response.raise_for_status.return_value = None
        response.text = SUPPORT_HTML
        return response

    monkeypatch.setattr(fetch.requests, "get", fake_get)

    source = fetch.probe_snaps("0287")

    assert source is not None
    assert source.package_type == "supportfiles"
