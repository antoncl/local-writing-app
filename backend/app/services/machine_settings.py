from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import yaml
from pydantic import BaseModel, Field

from app.models import (
    AIPolicy,
    AssistantTag,
    DisplaySettings,
    RecentProject,
    Swatch,
    UpdateChannel,
)
from app.services.project.errors import ProjectServiceError

APP_NAME = "local-writing-app"
CONFIG_FILENAME = "config.yaml"
ASSISTANT_TAGS_FILENAME = "assistant-tags.yaml"
MASK = "********"
RECENT_PROJECTS_MAX = 10

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "openrouter": "anthropic/claude-haiku-4.5",
    "ollama": "llama3.2",
}


# The seed palette. Exactly 30 swatches so the SwatchPicker grid fills
# its default 5×6 layout with no empty cells. The first four ids
# (forest, slate-blue, warm-brown, graphite) preserve the historical
# `--ctx-k-*` values from ContextPicker.svelte so the picker's chips
# and monograms keep their look once the hardcoded vars are removed.
# The rest is a writer-friendly spread across hues, picked to read on
# both light and dark backgrounds.
DEFAULT_PALETTE: list[dict[str, str]] = [
    {"id": "forest", "label": "Forest", "hex": "#3f7d68"},
    {"id": "slate-blue", "label": "Slate Blue", "hex": "#4f7390"},
    {"id": "warm-brown", "label": "Warm Brown", "hex": "#976b46"},
    {"id": "graphite", "label": "Graphite", "hex": "#5f6f67"},
    {"id": "sage", "label": "Sage", "hex": "#7a9b7e"},
    {"id": "moss", "label": "Moss", "hex": "#5b7a3a"},
    {"id": "olive", "label": "Olive", "hex": "#8a8a3a"},
    {"id": "mint", "label": "Mint", "hex": "#5fae8c"},
    {"id": "teal", "label": "Teal", "hex": "#3f7d80"},
    {"id": "ocean", "label": "Ocean", "hex": "#2f6680"},
    {"id": "sky", "label": "Sky", "hex": "#6f9fc4"},
    {"id": "navy", "label": "Navy", "hex": "#2d3f5e"},
    {"id": "indigo", "label": "Indigo", "hex": "#4a5896"},
    {"id": "lavender", "label": "Lavender", "hex": "#8c84bf"},
    {"id": "violet", "label": "Violet", "hex": "#6b4d8a"},
    {"id": "mauve", "label": "Mauve", "hex": "#8e6a7e"},
    {"id": "plum", "label": "Plum", "hex": "#8a3f6a"},
    {"id": "fuchsia", "label": "Fuchsia", "hex": "#b04590"},
    {"id": "rose", "label": "Rose", "hex": "#b0567a"},
    {"id": "crimson", "label": "Crimson", "hex": "#a8423f"},
    {"id": "brick", "label": "Brick", "hex": "#8a3f2a"},
    {"id": "coral", "label": "Coral", "hex": "#c46a52"},
    {"id": "rust", "label": "Rust", "hex": "#9a5a36"},
    {"id": "chocolate", "label": "Chocolate", "hex": "#704a2e"},
    {"id": "amber", "label": "Amber", "hex": "#c08a3a"},
    {"id": "ochre", "label": "Ochre", "hex": "#a08236"},
    {"id": "sand", "label": "Sand", "hex": "#c0a874"},
    {"id": "stone", "label": "Stone", "hex": "#7d7768"},
    {"id": "silver", "label": "Silver", "hex": "#94a09a"},
    {"id": "charcoal", "label": "Charcoal", "hex": "#3a423f"},
    # Standard signaling primaries — recognizable RAG + blue/orange + a
    # neutral. Picked to read as the literal color name (vs. the curated
    # tones above) and to tint well under color-mix(... 12%, white 88%).
    {"id": "red", "label": "Red", "hex": "#d44a4a"},
    {"id": "green", "label": "Green", "hex": "#3eaa5a"},
    {"id": "yellow", "label": "Yellow", "hex": "#d8b22a"},
    {"id": "blue", "label": "Blue", "hex": "#3a76d8"},
    {"id": "orange", "label": "Orange", "hex": "#e07a26"},
    {"id": "gray", "label": "Gray", "hex": "#8a948f"},
]


class ProviderCredentials(BaseModel):
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_host: str = "http://127.0.0.1:11434"


PROVIDER_DISPLAY_NAMES = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
}


def _seed_palette() -> list[Swatch]:
    return [Swatch(**entry) for entry in DEFAULT_PALETTE]


class MachineSettings(BaseModel):
    version: int = 1
    providers: ProviderCredentials = Field(default_factory=ProviderCredentials)
    default_provider: str = "ollama"
    default_models: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MODELS))
    default_projects_folder: str = ""
    recent_projects: list[RecentProject] = Field(default_factory=list)
    palette: list[Swatch] = Field(default_factory=_seed_palette)
    display: DisplaySettings = Field(default_factory=DisplaySettings)
    # The application-global default AI access policy (#746) — the outermost
    # fallback of the inheritance chain, resolved when a project states `inherit`
    # and nothing up its chain states a policy (`_AIPolicyResolver`'s seed). An
    # application-global preference like `display`/`palette`, not machine
    # substrate; it lives here because the config dir is the app's home outside
    # the projects, and the machine root folder is a bare container, not a
    # project that could carry it. No `inherit` — this IS the floor. Seeds `off`
    # (fail-closed, decisions_ai_permission_fails_closed).
    ai_policy: AIPolicy = "off"
    # The address the product entrypoint (app/server.py) binds when run as the
    # packaged app (ADR-0072 §3). Empty host / 0 port = unset -> loopback
    # default. A non-loopback host exposes an app that has NO authentication;
    # supported only for a single trusted user on a trusted private network.
    bind_host: str = ""
    bind_port: int = 0
    # Which GitHub Releases channel this install checks for updates (ADR-0072
    # S6, #1362). `stable` follows tagged `v*` releases; `nightly` follows the
    # rolling bleeding-edge prerelease. Default `stable` — an unconfigured
    # install should not be told a nightly is newer than its release.
    update_channel: UpdateChannel = "stable"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def reveal_config_dir() -> None:
    """Open the app-data dir (``config_dir()``) in the OS file manager (#1749).

    Platform-native: Explorer on Windows, Finder on macOS, ``xdg-open`` on Linux.
    That directory holds ``app.log`` (#1745) and ``errors.log`` (#386/#741); it is
    created if absent so the reveal never fails on a first run. The subprocess
    calls are ``check=False`` — a missing file manager (a headless host) should
    not raise; the caller only asked to *try* to show the folder.
    """
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(directory)  # type: ignore[attr-defined]  # Windows-only API
    elif sys.platform == "darwin":
        subprocess.run(["open", str(directory)], check=False)
    else:
        subprocess.run(["xdg-open", str(directory)], check=False)


def validated_projects_root(raw: str) -> str:
    """Check a projects root before it is stored, or refuse (#429).

    The bound used to be validated on the way in — `_validate_projects_base_folder`
    checked that a project's `projects_base_folder` existed, was a directory,
    and actually contained the project, raising 404/400 otherwise. Moving the
    bound to the machine tier deleted that check along with the key it guarded,
    and the value it now guards is **more** dangerous unvalidated, not less: a
    per-project mistake broke one project, whereas a mistyped machine root
    silently flattens the chain for *every* project at once, and the resulting
    validation warning blames each project for being "outside" a folder that
    does not exist.

    Empty is legal and means unset — the state of every machine before the
    setting is touched, and the way to deliberately clear it.

    Deliberately **not** checked: whether any particular project sits inside it.
    That is no longer this value's business — a project outside the root is
    #441's subject, and refusing to save a root because the currently-open
    project is outside it would make the setting unfixable from the one screen
    that edits it.
    """
    if not raw.strip():
        return ""
    try:
        folder = Path(raw).expanduser()
    except (OSError, ValueError) as exc:
        raise ProjectServiceError(f"Not a usable folder path: {raw}", 400) from exc
    if not folder.exists():
        raise ProjectServiceError(f"That projects folder does not exist: {folder}", 404)
    if not folder.is_dir():
        raise ProjectServiceError(f"The projects folder must be a folder: {folder}", 400)
    return str(folder.resolve())


def projects_root() -> Path | None:
    """The one folder the app works within — the outer bound of every layer
    walk (#429).

    The bound is **machine information**: there is exactly one root, so every
    project under it necessarily agrees about where the chain stops. It used to
    be `settings.projects_base_folder` in each project's own `project.yaml`,
    which meant an absolute path duplicated into every manifest on disk —
    surviving neither a move, nor another machine, nor a different drive
    letter — and, because the create wizard built each project directly under
    the folder it passed as the bound, always equal to the project's own
    parent. No two levels of one shelf ever agreed, so a chain enumerated
    exactly one hop from whichever end it was opened.

    Pre-1.0 the stored manifest key is simply ignored; there is no migration
    (`memory/feedback_no_pre_1_0_migrations.md`).

    **Read directly rather than through `load_settings()`, deliberately.**
    That function is a loader, not an accessor: it mutates the palette
    (`_top_up_palette`). This is called from `_metadata_schema_base_folder`,
    i.e. on every layer walk, i.e. on every node-index build. A read path must
    stay a pure read, and a walk must not carry a loader's side effects.

    Derived from `config_path()` like `assistants_dir()`, so the autouse test
    fixture that redirects the config path isolates this too — a test can never
    read or write the developer's real machine root.

    `None` when unset, empty or unreadable. That is the honest degradation: no
    bound means a project's chain is itself alone, which is what the app did
    for every project before a root was configured anyway.
    """
    path = config_path()
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("default_projects_folder")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return Path(raw).expanduser().resolve()
    except (OSError, ValueError):
        return None


def bind_address() -> tuple[str | None, int | None]:
    """The configured bind host/port, read directly from config.yaml (ADR-0072 §3).

    Read directly rather than through `load_settings()` for the same reason
    `projects_root()` is: this runs at process startup and a read path must not
    write (load_settings has side effects). Returns (None, None) components for
    anything unset/blank/unreadable, so the caller falls through to its default.
    """
    path = config_path()
    if not path.exists():
        return (None, None)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return (None, None)
    if not isinstance(data, dict):
        return (None, None)
    raw_host = data.get("bind_host")
    host = raw_host.strip() if isinstance(raw_host, str) and raw_host.strip() else None
    raw_port = data.get("bind_port")
    port = raw_port if isinstance(raw_port, int) and raw_port > 0 else None
    return (host, port)


def update_channel() -> UpdateChannel:
    """The configured update channel, read directly from config.yaml (ADR-0072 S6).

    A raw read, not `load_settings()`, for the same reason `default_ai_policy()`
    is: the update-check endpoint reads this, and a read path must not be able to
    write (load_settings materialises assistant files and tops up the palette).

    Falls back to `stable` for anything unset/blank/unreadable/out-of-set — the
    same fail-safe default as the model field: never silently follow nightly.
    """
    path = config_path()
    if not path.exists():
        return "stable"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return "stable"
    if not isinstance(data, dict):
        return "stable"
    value = data.get("update_channel")
    return value if value in get_args(UpdateChannel) else "stable"


def palette() -> list[Swatch]:
    """The machine colour palette, read directly — NOT via `load_settings()`.

    Same discipline as `projects_root()` / `default_ai_policy()`: a read path must
    not be able to write, and `load_settings()` can materialise assistant files
    and top up the palette. Snapping an AI-proposed colour onto a swatch (#696)
    is a read path. Falls back to the seed palette when unset/unreadable, and
    drops any malformed stored swatch rather than failing the read.
    """
    path = config_path()
    if not path.exists():
        return _seed_palette()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return _seed_palette()
    raw = data.get("palette") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return _seed_palette()
    swatches: list[Swatch] = []
    for entry in raw:
        try:
            swatches.append(Swatch.model_validate(entry))
        except Exception:  # noqa: BLE001 - skip a malformed swatch, keep the rest
            continue
    return swatches or _seed_palette()


def default_ai_policy() -> AIPolicy:
    """The application-global default AI policy (#746) — the outermost fallback
    of every project's inheritance chain, resolved when nothing up the chain
    states one (`_AIPolicyResolver`'s seed).

    **A raw read, not `load_settings()`, for the same reason `projects_root()`
    is.** This seeds `_resolved_ai_policy`, which runs on every AI route and on
    `current_project()` (project open) — a read/resolve path. `load_settings()`
    mutates the palette (`_top_up_palette`), and a read path must stay a pure
    read. So read the one field directly, isolated by the config-path redirect
    like `projects_root()`.

    Fail-closed: unset, unreadable, or out-of-set is `off`
    (`decisions_ai_permission_fails_closed`)."""
    path = config_path()
    if not path.exists():
        return "off"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return "off"
    if not isinstance(data, dict):
        return "off"
    value = data.get("ai_policy")
    return value if value in get_args(AIPolicy) else "off"


def is_within_root(path: Path, root: Path | None) -> bool:
    """Is `path` inside an already-resolved projects `root` — the #441
    availability test. Pure: no I/O, so a caller checking many paths (the
    settings view checks every recent) resolves the root once and reuses it.

    A project outside the root is treated as **unavailable**: the same as a
    folder that has been deleted. The equivalence is deliberate, and safe in a
    way a "does it still exist?" stat is not — it is a pure path comparison, so
    unlike a filesystem probe it never mis-flags a project that is merely on an
    unmounted drive (the case #423's recents design refuses to guess at).

    Permissive (`True`) when `root` is None: the create wizard establishes one
    before the app is usable, and the rare truly-unset state should not make
    *every* project look unavailable at once. So this only ever marks something
    out-of-root against a root the user actually set.
    """
    if root is None:
        return True
    try:
        path.expanduser().resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def is_within_projects_root(path: Path) -> bool:
    """`is_within_root` against the configured machine root, read once (#441).

    For a single path (e.g. the folder picker's shown folder). A caller testing
    many paths should read `projects_root()` itself and call `is_within_root`,
    rather than re-reading config.yaml per path.
    """
    return is_within_root(path, projects_root())


def assistants_dir() -> Path:
    """Folder holding assistant entry files. Derived from `config_path()` so
    test fixtures that patch the config path automatically isolate this too."""
    return config_path().parent / "assistants"


def assistant_tags_path() -> Path:
    """The machine-global assistant-tag vocabulary file (#88). Derived from
    config_path() so test fixtures patching the config path isolate it too."""
    return config_path().parent / ASSISTANT_TAGS_FILENAME


def error_log_dir() -> Path:
    """Folder holding the machine-scope `errors.log` (#741) — the config dir, a
    sibling of `config.yaml` — used when a failure has no project bound (a
    project-open failure, a landing-screen error). Derived from config_path() so
    test fixtures patching the config path isolate it too."""
    return config_path().parent


def load_assistant_tags() -> list[AssistantTag]:
    """Read the assistant-tag vocabulary; a missing/malformed file → empty."""
    path = assistant_tags_path()
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    raw = data.get("tags") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    tags: list[AssistantTag] = []
    for entry in raw:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"].strip():
            color = entry.get("color")
            tags.append(AssistantTag(name=entry["name"].strip(), color=color if isinstance(color, str) else None))
    return tags


def save_assistant_tags(tags: list[AssistantTag]) -> None:
    path = assistant_tags_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tags": [t.model_dump(mode="json") for t in tags]}
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def tag_names_from_field(raw: Any) -> list[str]:
    """A metadata tags field (a list, or a comma-separated string) → clean names.
    Mirrors the frontend readTags in assistantScope.ts."""
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def register_assistant_tags(names: Iterable[str]) -> list[AssistantTag]:
    """Add any not-yet-known tag names with color=None; never clobber an existing
    color. Returns the full updated vocabulary. This is what un-breaks the empty
    `[+]` picker — every tag a writer types on an assistant/prompt lands here."""
    tags = load_assistant_tags()
    existing = {t.name for t in tags}
    added = False
    for name in names:
        clean = name.strip()
        if clean and clean not in existing:
            tags.append(AssistantTag(name=clean, color=None))
            existing.add(clean)
            added = True
    if added:
        save_assistant_tags(tags)
    return tags


def set_assistant_tag_color(name: str, color: str | None) -> list[AssistantTag]:
    """Set (or clear) a tag's color, registering the tag if it's new."""
    clean = name.strip()
    tags = load_assistant_tags()
    for tag in tags:
        if tag.name == clean:
            tag.color = color
            break
    else:
        tags.append(AssistantTag(name=clean, color=color))
    save_assistant_tags(tags)
    return tags


def merge_assistant_tags(sources: Iterable[str], target: str) -> list[AssistantTag]:
    """Fold `sources` into `target` in the machine-global store (#247).

    The store half of an assistant-tag merge/rename — the document rewrite lives
    in AssistantTagsMixin, which calls this last. Case-insensitive on names; the
    survivor takes `target`'s casing. Like project `merge_tags`, the survivor
    keeps its OWN colour and the merged-away sources drop theirs with their
    records; a brand-new target has no colour. Order-preserving so the store
    file stays stable across a re-colour or re-merge.
    """
    clean_target = target.strip()
    target_lower = clean_target.lower()
    source_lowers = {
        source.strip().lower()
        for source in sources
        if source.strip() and source.strip().lower() != target_lower
    }
    result: list[AssistantTag] = []
    target_written = False
    for tag in load_assistant_tags():
        lower = tag.name.lower()
        if lower in source_lowers:
            continue  # merged away — its record (and colour) is dropped
        if lower == target_lower:
            if target_written:
                # The store can hold two casing variants of a name (register /
                # set-colour dedupe by EXACT name), and both match the target.
                # Write the survivor exactly ONCE — keeping the first record's
                # colour — so a merge can never emit a duplicate record.
                continue
            # Survivor keeps its own colour, but takes the requested casing.
            result.append(AssistantTag(name=clean_target, color=tag.color))
            target_written = True
        else:
            result.append(tag)
    if not target_written:
        result.append(AssistantTag(name=clean_target, color=None))
    save_assistant_tags(result)
    return result


def load_settings() -> MachineSettings:
    """Read config.yaml. The Slice A inline `assistants` list has been removed —
    assistant files are canonical and created explicitly (the create wizard's
    hire, the Assistants pane's "+"), never auto-seeded (#1413): a fresh install
    starts with an empty roster and AI calls resolve via the `default_models`
    fallback until the author hires one."""
    path = config_path()
    if not path.exists():
        settings = MachineSettings()
    else:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            settings = MachineSettings()
        else:
            if not isinstance(data, dict):
                settings = MachineSettings()
            else:
                # Drop legacy inline fields if a config from Slice A/B/C is
                # encountered — they're now ignored.
                data.pop("assistants", None)
                data.pop("default_assistant_id", None)
                try:
                    settings = MachineSettings.model_validate(data)
                except Exception:
                    settings = MachineSettings()
    _top_up_palette(settings)
    return settings


def _top_up_palette(settings: MachineSettings) -> None:
    """Append any seed swatches the user's stored palette is missing.

    Purely additive — never reorders, renames, or removes user swatches.
    Handles the seed growing over time without forcing existing users to
    manually re-add new colors. If the user *deleted* a seed swatch on
    purpose, it'll come back here; reset is a known limitation."""
    existing_ids = {s.id for s in settings.palette}
    appended: list[Swatch] = []
    for entry in DEFAULT_PALETTE:
        if entry["id"] not in existing_ids:
            appended.append(Swatch(**entry))
    if appended:
        settings.palette = list(settings.palette) + appended


def save_settings(settings: MachineSettings) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.model_dump(mode="json")
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def mask_credentials(settings: MachineSettings) -> dict[str, Any]:
    payload = settings.model_dump(mode="json")
    providers = payload.get("providers", {})
    for key in ("anthropic_api_key", "openai_api_key", "openrouter_api_key"):
        if providers.get(key):
            providers[key] = MASK
    payload["providers"] = providers
    return payload


def _apply_provider_patch(base: dict[str, Any], providers_patch: Any) -> None:
    """Merge a provider-credentials patch into `base` in place. A MASK sentinel
    or a None value means 'keep current' — so rotating one key never clears the
    others (which arrive masked on read)."""
    if not isinstance(providers_patch, dict):
        return
    providers = base.setdefault("providers", {})
    for key, value in providers_patch.items():
        if value is None or value == MASK:
            continue
        providers[key] = value


def merge_update(current: MachineSettings, patch: dict[str, Any]) -> MachineSettings:
    """Apply a partial update; MASK sentinels mean 'keep current value'."""
    base = current.model_dump(mode="json")
    # Plain scalar passthroughs: set when present and non-null. `ai_policy`'s
    # Literal bound on MachineSettings rejects a bad value at the final
    # model_validate, so an out-of-set string never persists.
    for key in ("default_provider", "ai_policy", "update_channel"):
        if key in patch and patch[key] is not None:
            base[key] = patch[key]
    if "default_models" in patch and isinstance(patch["default_models"], dict):
        base.setdefault("default_models", {}).update(patch["default_models"])
    if "default_projects_folder" in patch and patch["default_projects_folder"] is not None:
        base["default_projects_folder"] = validated_projects_root(patch["default_projects_folder"])
    if "recent_projects" in patch and patch["recent_projects"] is not None:
        # An explicit list rewrites the recents — used when the user removes
        # a stale entry from the UI.
        base["recent_projects"] = patch["recent_projects"]
    if "palette" in patch and patch["palette"] is not None:
        # The palette is edited as a whole list in the settings UI — reorder,
        # add, rename, delete all yield a new list. Validate via Pydantic so
        # malformed swatches (bad hex, empty id) raise before save.
        base["palette"] = [
            Swatch.model_validate(s).model_dump(mode="json")
            for s in patch["palette"]
        ]
    _apply_provider_patch(base, patch.get("providers"))
    display_patch = patch.get("display")
    if isinstance(display_patch, dict):
        # The three prose-presentation fields travel together from the UI; the
        # ui_scale clamp runs in DisplaySettings on the final model_validate.
        display = base.setdefault("display", {})
        for key in ("ui_scale", "paragraph_align", "paragraph_indent"):
            if key in display_patch and display_patch[key] is not None:
                display[key] = display_patch[key]
    return MachineSettings.model_validate(base)


def touch_recent_project(root_path: Path, title: str) -> None:
    """Move-to-top a project on the recents list. Cap at RECENT_PROJECTS_MAX.

    Best-effort: any failure (read-only config dir, malformed yaml) is
    swallowed — recents is UX polish, not a correctness path. The create /
    open flows must not break because of a recents-write hiccup.
    """
    try:
        path_str = str(root_path.expanduser().resolve())
        now_iso = datetime.now(UTC).isoformat(timespec="seconds")
        settings = load_settings()
        kept = [r for r in settings.recent_projects if r.path != path_str]
        kept.insert(0, RecentProject(path=path_str, title=title, opened_at=now_iso))
        settings.recent_projects = kept[:RECENT_PROJECTS_MAX]
        save_settings(settings)
    except Exception:  # noqa: BLE001
        # Don't let recents tracking break project open/create.
        pass


# Assistant files are created explicitly (create-wizard hire / Assistants pane
# "+"), never auto-seeded — the old first-run `default_models` → files seeder was
# removed once the wizard hires explicitly (#1413).
