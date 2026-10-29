import pytest

from mht.utils.gh_category_history import (
    lookup_gh_category,
    normalise_release,
)


@pytest.fixture
def catalogue():
    return {
        "machines": {
            "example": {
                "observations": {
                    "0281": ["Arcade"],
                    "0283": ["Arcade"],
                    "0284": ["Gambling"],
                    "0287": ["Gambling"],
                }
            },
            "newgame": {
                "observations": {
                    "0286": ["Arcade"],
                }
            },
        }
    }


def test_release_normalisation():
    assert normalise_release(287) == "0287"
    assert normalise_release("0287") == "0287"
    assert normalise_release("0.287") == "0287"


def test_exact_observation(catalogue):
    result = lookup_gh_category(
        catalogue, "example", "0281"
    )

    assert result["category"] == ["Arcade"]
    assert result["source_release"] == "0281"
    assert result["status"] == "observed"


def test_missing_intermediate_release(catalogue):
    result = lookup_gh_category(
        catalogue, "example", "0282"
    )

    assert result["category"] == ["Arcade"]
    assert result["source_release"] == "0281"
    assert result["status"] == "carried_forward"


def test_latest_observation_for_future_release(catalogue):
    result = lookup_gh_category(
        catalogue, "example", "0289"
    )

    assert result["category"] == ["Gambling"]
    assert result["source_release"] == "0287"
    assert result["status"] == "carried_forward"


def test_no_future_information(catalogue):
    assert lookup_gh_category(
        catalogue, "newgame", "0285"
    ) is None


def test_unknown_machine(catalogue):
    assert lookup_gh_category(
        catalogue, "not_in_catalogue", "0289"
    ) is None


def test_category_change(catalogue):
    before = lookup_gh_category(
        catalogue, "example", "0283"
    )
    after = lookup_gh_category(
        catalogue, "example", "0284"
    )

    assert before["category"] == ["Arcade"]
    assert after["category"] == ["Gambling"]


def test_returned_categories_are_independent(catalogue):
    result = lookup_gh_category(
        catalogue, "example", "0287"
    )

    result["category"].append("Hardware")

    assert catalogue["machines"]["example"][
        "observations"
    ]["0287"] == ["Gambling"]


@pytest.mark.parametrize(
    "release",
    ["invalid", "", "0.28x", -1, True],
)
def test_invalid_release_rejected(release):
    with pytest.raises(ValueError):
        normalise_release(release)


from mht.utils.gh_category_history import (
    build_gh_category_snapshot,
)


@pytest.mark.parametrize(
    "release",
    ["0280", "0281", "0282", "0283", "0284", "0287", "0289"],
)
def test_snapshot_matches_individual_lookup(
    catalogue, release
):
    snapshot = build_gh_category_snapshot(
        catalogue, release
    )

    for machine in catalogue["machines"]:
        assert snapshot.get(machine) == lookup_gh_category(
            catalogue, machine, release
        )


def test_snapshot_preserves_missing_observation(catalogue):
    snapshot = build_gh_category_snapshot(
        catalogue, "0282"
    )

    assert snapshot["example"]["category"] == ["Arcade"]
    assert snapshot["example"]["source_release"] == "0281"
    assert snapshot["example"]["status"] == "carried_forward"


def test_snapshot_does_not_mutate_history(catalogue):
    snapshot = build_gh_category_snapshot(
        catalogue, "0289"
    )

    snapshot["example"]["category"].append("Hardware")

    assert catalogue["machines"]["example"][
        "observations"
    ]["0287"] == ["Gambling"]
