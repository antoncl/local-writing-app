"""Where the built frontend bundle lives, so the backend can serve it (ADR-0072 §1).

One process, one origin: in a packaged build the API and UI share an origin
because this same server serves the bundle. This module is the single seam that
locates it — a source run finds `<repo>/frontend/dist`; the frozen build (ADR-0072
slice S3) will add a `sys._MEIPASS` branch here and nowhere else.
"""

from __future__ import annotations

import sys
from pathlib import Path


def frontend_dist_dir() -> Path | None:
    """The built frontend bundle directory, or None if it isn't present.

    None is the honest degradation for a dev run: the backend serves the API
    only and the Vite dev server serves the UI (cross-origin, per the CORS
    regex in main.py). When a build exists (packaged product, or a local
    `npm run build`), the same server serves it and the UI is same-origin.
    """
    # Frozen build (PyInstaller, ADR-0072 S3): the bundle is collected beside
    # the app under _MEIPASS/frontend_dist.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / "frontend_dist"
        return candidate if candidate.is_dir() else None
    # Source run: backend/app/services/frontend_assets.py -> parents[3] = <repo>.
    candidate = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return candidate if candidate.is_dir() else None
