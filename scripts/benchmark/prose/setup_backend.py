"""Per-run backend setup for the prose harness (#2613, measuring-prose-quality.md §7 "Setup").

Against the discovered dev backend (never :8787):
  1. Provider keys. For every non-ollama provider the model list needs, read the
     key from the environment and write it with `PUT /api/settings/machine
     {"providers": {"<provider>_api_key": value}}` (routers/machine_settings.py;
     models/ai.py::ProviderCredentialsPatch). The dev backend runs with a
     throwaway `LWA_CONFIG_DIR` (scripts/dev_backend.py), so this never touches
     the user's real config. A key is never printed or logged.
  2. Per case project: `PATCH /api/project/settings {"ai_policy": ...}`
     (routers/project.py::update_project_settings) - `cloud-allowed` if any
     non-ollama model is listed, else `local-only`.
  3. Per project and model: an assistant, `POST /api/assistants` then
     `PUT /api/assistants/{id}` (routers/entries.py ~L105-130) with the
     `ai_provider / ai_model / ai_max_tokens / ai_temperature / ai_thinking`
     metadata keys (services/ai/call_resolver.py reads exactly these). It is read
     back and checked: an unknown assistant id silently falls back to defaults,
     so the harness asserts the id exists and carries the settings.

The assistant ids are recorded in each case's `fixture.json` under `assistants`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_gen import CASES, load_fixture, write_fixture  # noqa: E402
from lwa_client import ApiError, Client, discover_backend  # noqa: E402

HERE = Path(__file__).resolve().parent
KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def load_models(path: Path | None = None) -> list[dict[str, Any]]:
    """`models.yaml` if present beside this file, else `models.example.yaml`."""
    chosen = path or next(p for p in (HERE / "models.yaml", HERE / "models.example.yaml") if p.is_file())
    models = yaml.safe_load(chosen.read_text(encoding="utf-8"))["models"]
    if not models:
        raise SystemExit(f"{chosen} lists no models.")
    return models


def select_models(models: list[dict[str, Any]], names: list[str] | None) -> list[dict[str, Any]]:
    if not names:
        return models
    chosen = [m for m in models if m["name"] in names]
    missing = set(names) - {m["name"] for m in chosen}
    if missing:
        raise SystemExit(f"Unknown model name(s): {', '.join(sorted(missing))}")
    return chosen


def provider_keys(models: list[dict[str, Any]]) -> dict[str, str]:
    """`{<provider>_api_key: value}` from the environment; exit naming a missing variable."""
    patch: dict[str, str] = {}
    for provider in sorted({m["provider"] for m in models} - {"ollama"}):
        env_name = KEY_ENV.get(provider)
        if env_name is None:
            raise SystemExit(f"Unknown provider {provider!r}; expected one of ollama, {', '.join(KEY_ENV)}.")
        value = os.environ.get(env_name, "")
        if not value:
            raise SystemExit(f"Set {env_name} in the environment (needed for provider {provider!r}).")
        patch[f"{provider}_api_key"] = value
    return patch


def ai_policy_for(models: list[dict[str, Any]]) -> str:
    return "cloud-allowed" if any(m["provider"] != "ollama" for m in models) else "local-only"


def assistant_metadata(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "ai_provider": model["provider"],
        "ai_model": model["model"],
        "ai_max_tokens": model["max_tokens"],
        "ai_temperature": model["temperature"],
        "ai_thinking": False,
    }


def _existing_assistant(project: Client, assistant_id: str | None) -> dict[str, Any] | None:
    if not assistant_id:
        return None
    try:
        return project.get(f"/api/assistants/{assistant_id}")
    except ApiError:
        return None


def ensure_assistant(project: Client, model: dict[str, Any], known_id: str | None) -> str:
    """Create (or reuse) the model's assistant, save its settings, read them back."""
    entry = _existing_assistant(project, known_id)
    if entry is None:
        entry = project.post("/api/assistants", {"title": model["name"], "layer_id": None})
    metadata = assistant_metadata(model)
    project.put(
        f"/api/assistants/{entry['id']}",
        {
            "title": model["name"],
            "base_revision": entry["revision"],
            "entry_type": entry["entry_type"],
            "metadata": metadata,
        },
    )
    back = project.get(f"/api/assistants/{entry['id']}")
    wrong = {k: back["metadata"].get(k) for k, v in metadata.items() if back["metadata"].get(k) != v}
    if wrong:
        raise SystemExit(f"Assistant {entry['id']} for {model['name']} did not keep its settings: {wrong}")
    return entry["id"]


def setup_case(base_url: str, case: str, models: list[dict[str, Any]]) -> None:
    fixture = load_fixture(case)
    project = Client(base_url, fixture["root"])
    try:
        project.patch("/api/project/settings", {"ai_policy": ai_policy_for(models)})
        known = fixture.get("assistants", {})
        fixture["assistants"] = {
            **known,
            **{m["name"]: ensure_assistant(project, m, known.get(m["name"])) for m in models},
        }
    finally:
        project.close()
    write_fixture(case, fixture)
    print(f"{case}: policy {ai_policy_for(models)}, assistants {sorted(fixture['assistants'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--models", nargs="+", help="model names from models.yaml (default: all)")
    args = parser.parse_args()
    base_url = discover_backend()
    models = select_models(load_models(), args.models)
    keys = provider_keys(models)
    if keys:
        # The machine-settings route is unscoped; the key is sent, never echoed.
        Client(base_url).put("/api/settings/machine", {"providers": keys})
        print(f"wrote provider keys for: {', '.join(k.removesuffix('_api_key') for k in keys)}")
    for case in args.cases:
        setup_case(base_url, case, models)


if __name__ == "__main__":
    main()
