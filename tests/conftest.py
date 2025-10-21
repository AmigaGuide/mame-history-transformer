import sys
import pathlib
import json
import pytest

# Keep your original src/ import path shim
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

# ---------- Path roots ----------

@pytest.fixture(scope="session")
def project_root() -> pathlib.Path:
    """Repository root = tests/.."""
    return pathlib.Path(__file__).resolve().parents[1]

@pytest.fixture(scope="session")
def data_dir(project_root) -> pathlib.Path:
    """data/ folder at repo root."""
    return project_root / "data"

# ---------- Resolve the active release from data/current_version.txt ----------

def _normalise_release_key(ver: str) -> str:
    """
    Convert '0.281' -> '0281' (pad the minor with 3 digits).
    If format is unexpected, fall back to stripping non-digits.
    """
    ver = (ver or "").strip()
    # Expected: '0.xxx' (MAME style)
    if ver.startswith("0.") and ver[2:].isdigit():
        return ver[0] + ver[2:].zfill(3)  # '0' + '281' -> '0281'
    # Fallback: digits only
    digits = "".join(ch for ch in ver if ch.isdigit())
    return digits or "0000"

@pytest.fixture(scope="session")
def current_version_str(data_dir) -> str:
    """
    Read data/current_version.txt and return its raw string (e.g. '0.281').
    Fail with a clear message if missing.
    """
    fp = data_dir / "current_version.txt"
    if not fp.exists():
        pytest.fail(
            f"Expected {fp.as_posix()} to exist so tests know which release to read.\n"
            f"Create the file with the active MAME version (e.g. '0.281').",
            pytrace=False,
        )
    return fp.read_text(encoding="utf-8").strip()

@pytest.fixture(scope="session")
def release_key(current_version_str) -> str:
    """Return folder key like '0281' derived from current_version_str."""
    return _normalise_release_key(current_version_str)

# ---------- Per-release directories ----------

@pytest.fixture(scope="session")
def release_dir(data_dir, release_key) -> pathlib.Path:
    p = data_dir / "releases" / release_key
    if not p.exists():
        pytest.fail(
            f"Release directory not found: {p.as_posix()}\n"
            f"Ensure outputs are generated for version set in data/current_version.txt.",
            pytrace=False,
        )
    return p

@pytest.fixture(scope="session")
def outputs_dir(release_dir) -> pathlib.Path:
    p = release_dir / "outputs"
    if not p.exists():
        pytest.fail(
            f"Outputs directory not found: {p.as_posix()}\n"
            f"Run the pipeline to generate outputs for the active release.",
            pytrace=False,
        )
    return p

@pytest.fixture(scope="session")
def summaries_dir(release_dir) -> pathlib.Path:
    return release_dir / "summaries"

@pytest.fixture(scope="session")
def archives_dir(release_dir) -> pathlib.Path:
    return release_dir / "archives"

# ---------- Small helpers ----------

@pytest.fixture(scope="session")
def read_json():
    def _load(p: pathlib.Path):
        if not p.exists():
            pytest.fail(f"Missing file for test: {p.as_posix()}", pytrace=False)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            pytest.fail(f"Failed to parse JSON at {p.as_posix()}: {e}", pytrace=False)
    return _load

@pytest.fixture(scope="session")
def require_file():
    def _req(p: pathlib.Path) -> pathlib.Path:
        if not p.exists():
            pytest.fail(f"Required file not found: {p.as_posix()}", pytrace=False)
        return p
    return _req
