from pathlib import Path

def check_required_files() -> bool:
    """
    Verifies that the required XML files are present in the /data folder.
    Returns True if all files are found, otherwise prints instructions and returns False.
    """
    data_dir = Path("data")
    mame_file = data_dir / "mame.xml"
    history_file = data_dir / "history.xml"

    missing = []

    if not mame_file.is_file():
        missing.append("mame.xml")

    if not history_file.is_file():
        missing.append("history.xml")

    if missing:
        print("\nMissing required files in /data:")
        for fname in missing:
            print(f" - {fname}")

        print("\nInstructions:")

        if "mame.xml" in missing:
            print("• Download the MAME XML from https://www.mamedev.org/release.php")
            print("• Extract the file from the mameXXXXlx.zip archive")
            print("• Rename the extracted file to 'mame.xml'")
            print("• Move it to the 'data' folder")

        if "history.xml" in missing:
            print("• Download the Gaming-History XML from:")
            print("  https://www.arcade-history.com/index.php?page=download")
            print("• Extract 'history.xml' from inside the 'history' folder of the ZIP")
            print("• Move it to the 'data' folder")

        return False

    return True

def main():
    print("Starting TM470 XML parsing pipeline...\n")

    if not check_required_files():
        print("Aborting. Required files missing.")
        return

    print("All required files found. Ready to begin parsing.")
    # Future calls to:
    # parse_mame_xml()
    # parse_history_xml()
    # transform_data()
    # write_output()

if __name__ == "__main__":
    main()
