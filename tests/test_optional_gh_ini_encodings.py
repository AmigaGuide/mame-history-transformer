from zipfile import ZipFile

from mht.utils.encoding_utils import detect_encodings_from_archives


LEAVES = {
    "mame_xml": "mame.xml",
    "history_xml": "history.xml",
    "ini_game": "[GAMING HISTORY] Game Or No Game.ini",
    "ini_category": "[GAMING HISTORY] Machine Category.ini",
    "ini_type": "[GAMING HISTORY] Machine Type.ini",
}


def test_missing_gh_ini_does_not_reuse_cached_data(tmp_path):
    mame_zip = tmp_path / "mame0287.zip"
    history_zip = tmp_path / "history287.zip"

    with ZipFile(mame_zip, "w") as archive:
        archive.writestr(
            "mame.xml",
            '<mame build="0.287"></mame>',
        )

    with ZipFile(history_zip, "w") as archive:
        archive.writestr(
            "history.xml",
            '<history version="0.287a"></history>',
        )
        archive.writestr(
            LEAVES["ini_game"],
            "[Game]\npuckman\n",
        )
        archive.writestr(
            LEAVES["ini_type"],
            "[Arcade]\npuckman\n",
        )

    missing_leaf = LEAVES["ini_category"]

    prior = {
        missing_leaf: {
            "encoding": "windows-1252",
            "zip_archive": "old_history.zip",
        }
    }

    result, changed = detect_encodings_from_archives(
        mame_archive=mame_zip,
        history_archive=history_zip,
        canonical_leaves=LEAVES,
        prior=prior,
    )

    assert changed is True
    assert missing_leaf not in result
    assert LEAVES["ini_game"] in result
    assert LEAVES["ini_type"] in result
    assert LEAVES["mame_xml"] in result
    assert LEAVES["history_xml"] in result


def test_missing_gh_ini_without_prior_cache(tmp_path):
    mame_zip = tmp_path / "mame0287.zip"
    history_zip = tmp_path / "history287.zip"

    with ZipFile(mame_zip, "w") as archive:
        archive.writestr(
            "mame.xml",
            '<mame build="0.287"></mame>',
        )

    with ZipFile(history_zip, "w") as archive:
        archive.writestr(
            "history.xml",
            '<history version="0.287a"></history>',
        )

    result, changed = detect_encodings_from_archives(
        mame_archive=mame_zip,
        history_archive=history_zip,
        canonical_leaves=LEAVES,
        prior={},
    )

    assert changed is True
    assert LEAVES["mame_xml"] in result
    assert LEAVES["history_xml"] in result

    for key in ("ini_game", "ini_category", "ini_type"):
        assert LEAVES[key] not in result
