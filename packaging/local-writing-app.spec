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

# Bake the build stamp: the commit this binary is frozen at (ADR-0072 S6, #1362).
# CI sets GITHUB_SHA for every step; a local freeze has none -> empty -> the
# runtime reads it back as None ("no stamp"). The nightly update check compares
# this because every nightly reports the same version string.
from app.services.build_info import BUILD_STAMP_FILENAME  # noqa: E402

_stamp_file = os.path.join(tempfile.mkdtemp(), BUILD_STAMP_FILENAME)
with open(_stamp_file, "w", encoding="utf-8") as _f:
    _f.write(os.environ.get("GITHUB_SHA", ""))
datas += [(_stamp_file, ".")]

# The app mark on the Windows exe + its Add/Remove-Programs entry (ADR-0072 S5).
# macOS gets .icns via the dmg build; other platforms take PyInstaller's default.
_exe_icon = None
if sys.platform == "win32":
    _win_ico = os.path.join(_repo_root, "packaging", "icons", "icon.ico")
    _exe_icon = _win_ico if os.path.isfile(_win_ico) else None

# macOS .app icon — built from icon-1024.png by packaging/macos/make-icns.sh
# before this spec runs (ADR-0072 S5).
_bundle_icon = None
if sys.platform == "darwin":
    _icns = os.path.join(_repo_root, "packaging", "icons", "icon.icns")
    _bundle_icon = _icns if os.path.isfile(_icns) else None

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

# macOS: wrap the onedir in a .app bundle for the drag-to-Applications dmg
# (ADR-0072 S5). Unsigned/experimental. The onedir COLLECT above is untouched,
# so the --self-check smoke and the zip still use it.
if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name="Local Writing App.app",
        icon=_bundle_icon,
        bundle_identifier="com.localwritingapp.app",
    )
