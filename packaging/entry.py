"""PyInstaller entry point (ADR-0072 S3).

The frozen product funnels through the same `app.server:main` as `python -m app`
and the console script — one bind-resolution + serve path, no reload.
"""
from app.server import main

if __name__ == "__main__":
    main()
