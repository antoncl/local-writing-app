# PyInstaller spec — the frozen product (ADR-0072 S3, #1344). Onedir.
# Build from repo root:  pyinstaller packaging/local-writing-app.spec --noconfirm
import os

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

a = Analysis(
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
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="local-writing-app",
)
