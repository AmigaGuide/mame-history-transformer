from __future__ import annotations

"""
MHT Web Preview server entry point.

This module intentionally stays small:
- load preview artefacts once
- construct Flask app
- run server (no reloader)
"""

import threading
import webbrowser
from typing import Optional

from mht.utils.config import WEB_PREVIEW_AUTO_OPEN, WEB_PREVIEW_PORT
from mht.utils.logger import setup_logger

from .app import create_app
from .loaders import load_preview_data

log = setup_logger(__name__)


def run_preview(port: int | None = None, auto_open: Optional[bool] = None) -> None:
    """
    Start the web preview server for the active release.

    Responsibilities:
    - Verify required JSON artefacts exist and load into memory once.
    - Start a Flask app on the configured port (reloader disabled).
    - Optionally open a browser pointing at '/'.

    Note:
    - We keep debug=False and use_reloader=False to avoid loading artefacts twice.
    """
    port = port or WEB_PREVIEW_PORT
    if auto_open is None:
        auto_open = WEB_PREVIEW_AUTO_OPEN

    try:
        preview_data = load_preview_data()
    except Exception as exc:  # noqa: BLE001
        log.error("Cannot start web preview: %s", exc)
        return

    app = create_app(preview_data)

    url = f"http://127.0.0.1:{port}/"
    log.info("Starting MHT web preview on %s", url)

    if auto_open:

        def _open_browser() -> None:
            webbrowser.open(url)

        threading.Timer(0.8, _open_browser).start()

    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run_preview()
