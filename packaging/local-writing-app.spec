# PyInstaller spec — the frozen product (ADR-0072 S3, #1344). Onedir.
# Build from repo root:  pyinstaller packaging/local-writing-app.spec --noconfirm
import os
import sys
import tempfile

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

# SPECPATH = the packaging/ dir (PyInstaller injects it); repo root is its parent.
_repo_root = os.path.dirname(SPECPATH)  # noqa: F821  (SPECPATH is a PyInstaller global)
_frontend_dist = os.path.join(_repo_root, "frontend", "dist")
_backend = os.path.join(_repo_root, "backend")

datas = []
binaries = []
hiddenimports = []

# All backend package data: the built-in Library (app/builtin_library/**/*.md,
# resolved via importlib.resources.files("app")) and _baked_in.yaml.
datas += collect_data_files("app")
# Package metadata so importlib.metadata.version("local-writing-service") resolves.
datas += copy_metadata("local-writing-service")
# The built frontend, where frontend_assets' frozen branch looks: _MEIPASS/frontend_dist.
datas += [(_frontend_dist, "frontend_dist")]

# Packages that pull implementations dynamically (add more here as the verify
# run surfaces ModuleNotFoundError at runtime).
for _pkg in ("uvicorn", "tiktoken"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# Bake the node-index build identity: the frozen app can't walk its own source
# .py (they're archived), so compute node_index_snapshot.build_identity() here —
# the source IS on disk in the build env — and ship the digest as data for the
# runtime to read (ADR-0072 freeze fix, #1348).
sys.path.insert(0, _backend)
from app.services.project.node_index_snapshot import (  # noqa: E402
    FROZEN_IDENTITY_FILENAME,
    build_identity,
)

_ident_file = os.path.join(tempfile.mkdtemp(), FROZEN_IDENTITY_FILENAME)
with open(_ident_file, "w", encoding="utf-8") as _f:
    _f.write(build_identity())
datas += [(_ident_file, ".")]

# The app mark on the Windows exe + its Add/Remove-Programs entry (ADR-0072 S5).
# macOS gets .icns via the dmg build; other platforms take PyInstaller's default.
_exe_icon = None
if sys.platform == "win32":
    _win_ico = os.path.join(_repo_root, "packaging", "icons", "icon.ico")
    _exe_icon = _win_ico if os.path.isfile(_win_ico) else None

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "entry.py")],  # noqa: F821
    pathex=[_backend],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="local-writing-app",
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=_exe_icon,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="local-writing-app",
)
