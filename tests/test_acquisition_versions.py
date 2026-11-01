import pytest

from mht.provenance.acquisition import (
    compare_embedded_release,
    release_from_embedded_version,
)


@pytest.mark.parametrize(
    ("provider", "version", "expected"),
    [
        ("mame", "0.287 (mame0287)", "0287"),
        ("mame", "0.288 (mame0288)", "0288"),
        ("mame", "0.289 (mame0289)", "0289"),
        ("gaming_history", "2.87a", "0287"),
        ("gaming_history", "2.88", "0288"),
        ("gaming_history", "2.89", "0289"),
        ("snaps", "0.287", "0287"),
        ("snaps", "0.288", "0288"),
        ("snaps", "0.289", "0289"),
    ],
)
def test_provider_version_normalisation(
    provider,
    version,
    expected,
):
    assert release_from_embedded_version(
        provider, version
    ) == expected


def test_embedded_release_matches():
    result = compare_embedded_release(
        "gaming_history",
        "2.87a",
        "0287",
    )

    assert result["status"] == "match"
    assert result["embedded_release"] == "0287"
    assert result["original_version"] == "2.87a"


def test_embedded_release_mismatch():
    result = compare_embedded_release(
        "snaps",
        "0.288",
        "0289",
    )

    assert result["status"] == "mismatch"


def test_missing_embedded_version_is_unverified():
    result = compare_embedded_release(
        "mame",
        None,
        "0289",
    )

    assert result["status"] == "unverified"
    assert result["embedded_release"] is None


def test_unrecognised_version_is_unverified():
    result = compare_embedded_release(
        "gaming_history",
        "unknown",
        "0289",
    )

    assert result["status"] == "unverified"
