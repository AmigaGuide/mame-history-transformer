import pytest

from mht.provenance.snaps_sources import resolve_snaps_source


SUPPORT_HTML = """
<a href="/download/?file=%2Fsupport%2Fpacks%2F_old%2FpS_SupportFiles_287.zip&amp;tipo=support_pack">
    Download 0.287
</a>
<a href="/download/?file=%2Fsupport%2Fpacks%2F_old%2FpS_SupportFiles_286.zip&amp;tipo=support_pack">
    Download 0.286
</a>
"""

CATVER_HTML = """
<a href="/download/?file=pS_CatVer_289.zip&amp;tipo=catver">
    Download CatVer 0.289
</a>
"""


def test_historical_release_uses_support_pack():
    source = resolve_snaps_source(
        "0287",
        support_html=SUPPORT_HTML,
        catver_html=CATVER_HTML,
    )

    assert source is not None
    assert source.release == "0287"
    assert source.package_type == "supportfiles"
    assert source.filename == "pS_SupportFiles_287.zip"


def test_matching_catver_takes_precedence():
    catver_html = CATVER_HTML + """
    <a href="/download/?file=pS_CatVer_287.zip&amp;tipo=catver">
        Download CatVer 0.287
    </a>
    """

    source = resolve_snaps_source(
        "0287",
        support_html=SUPPORT_HTML,
        catver_html=catver_html,
    )

    assert source is not None
    assert source.package_type == "catver"


def test_no_newer_release_substitution():
    source = resolve_snaps_source(
        "0288",
        support_html=SUPPORT_HTML,
        catver_html=CATVER_HTML,
    )

    assert source is None


def test_invalid_release_is_rejected():
    with pytest.raises(ValueError):
        resolve_snaps_source(
            "latest",
            support_html=SUPPORT_HTML,
            catver_html=CATVER_HTML,
        )


def test_unrelated_zip_is_ignored():
    html = """
    <a href="/download/?file=pS_Category_287.zip&amp;tipo=category">
        Other package
    </a>
    """

    source = resolve_snaps_source(
        "0287",
        support_html=html,
        catver_html="",
    )

    assert source is None


def test_duplicate_identical_download_links_are_accepted():
    link = (
        '<a href="/download/?file=pS_SupportFiles_288.zip'
        '&amp;tipo=support_pack">Download</a>'
    )

    source = resolve_snaps_source(
        "0288",
        support_html=link + link,
        catver_html="",
    )

    assert source is not None
    assert source.filename == "pS_SupportFiles_288.zip"



def test_current_support_pack_preferred_over_old_location():
    html = """
    <a href="/download/?tipo=support_pack&amp;file=/support/packs/pS_SupportFiles_288.zip">
        Current
    </a>
    <a href="/download/?tipo=support_pack&amp;file=/support/packs/_old/pS_SupportFiles_288.zip">
        Historical
    </a>
    """

    source = resolve_snaps_source(
        "0288",
        support_html=html,
        catver_html="",
    )

    assert source is not None
    assert source.package_type == "supportfiles"
    assert (
        "/support/packs/pS_SupportFiles_288.zip"
        in source.url
    )


def test_unrecognised_duplicate_locations_remain_ambiguous():
    html = """
    <a href="/download/?tipo=support_pack&amp;file=/archive-a/pS_SupportFiles_288.zip">
        Archive A
    </a>
    <a href="/download/?tipo=support_pack&amp;file=/archive-b/pS_SupportFiles_288.zip">
        Archive B
    </a>
    """

    with pytest.raises(ValueError, match="Multiple supportfiles"):
        resolve_snaps_source(
            "0288",
            support_html=html,
            catver_html="",
        )
