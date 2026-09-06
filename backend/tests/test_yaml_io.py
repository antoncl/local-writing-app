"""`load_yaml` is `yaml.safe_load` with a faster engine — same objects, same errors (#1847)."""

from __future__ import annotations

import importlib
import io
from datetime import date
from pathlib import Path

import pytest
import yaml

import app
from app.services import yaml_io
from app.services.yaml_io import SAFE_LOADER, load_yaml

# The YAML shapes the app writes: `safe_dump(sort_keys=False, allow_unicode=True)`
# front matter — nested metadata, ref lists, block scalars, unicode, the scalar
# types the resolver turns into non-strings, and the unquoted-ISO-date trap
# `lifecycle.py` documents. The pure-Python and libyaml scanners must agree on
# every one of them.
DOCUMENTS = [
    "id: scene_0f3c\ntitle: 'The Collective: Part One'\nentry_type: scene\n",
    "metadata:\n  pov: character_9a1\n  related_entries:\n    - lore_1\n    - lore_2\n  tags: []\n"
    "  weight: 0.75\n  count: 3\n  draft: true\n  note: null\n",
    "brief: |\n  Line one.\n\n  ---\n  Line after a dash line.\nsummary: >-\n  folded\n  text\n",
    "title: Ærø — «Ægir» 🐉 ‘quotes’\naliases:\n  - naïve\n  - 東京\n",
    "created: 2026-09-06\nupdated: '2026-09-06'\nwhen: 2026-09-06T10:00:00Z\n",
    "messages:\n  - role: user\n    content: \"hello\\nworld\"\n  - role: assistant\n    content: ''\n",
    "a: &anchor\n  x: 1\nb: *anchor\n",
    "",
    "# only a comment\n",
    "- just\n- a list\n",
    "scalar\n",
]


@pytest.mark.parametrize("text", DOCUMENTS)
def test_load_yaml_matches_safe_load(text: str) -> None:
    assert load_yaml(text) == yaml.safe_load(text)


def test_scalar_types_survive_the_engine_swap() -> None:
    data = load_yaml(DOCUMENTS[1])["metadata"]
    assert isinstance(data["weight"], float)
    assert isinstance(data["count"], int)
    assert data["draft"] is True
    assert data["note"] is None
    dates = load_yaml(DOCUMENTS[4])
    assert isinstance(dates["created"], date)
    assert dates["updated"] == "2026-09-06"


def test_round_trips_what_the_writers_emit() -> None:
    front_matter = {
        "id": "lore_7",
        "title": "Ægir: the sea",
        "metadata": {"related_entries": ["lore_1"], "text": "one\ntwo\n", "n": 2},
    }
    dumped = yaml.safe_dump(front_matter, sort_keys=False, allow_unicode=True)
    assert load_yaml(dumped) == front_matter


def test_accepts_text_and_binary_streams() -> None:
    assert load_yaml(io.StringIO("a: 1\n")) == {"a": 1}
    assert load_yaml(io.BytesIO(b"a: 1\n")) == {"a": 1}


@pytest.mark.parametrize(
    "text",
    [
        "fields: [ this is: not valid yaml\n",
        "a: b\n c: d\n",
        "\tindented: with a tab\n",
    ],
)
def test_malformed_input_raises_the_same_error_family(text: str) -> None:
    # Every caller keeps its `except yaml.YAMLError`; both engines must land in it.
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(text)
    with pytest.raises(yaml.YAMLError):
        load_yaml(text)


@pytest.mark.parametrize(
    "text",
    [
        # `FullLoader` refuses the first but constructs the other two; only a
        # *safe* loader refuses all three. "Safe" is the invariant; speed is the feature.
        "!!python/object/apply:os.system ['echo x']\n",
        "!!python/name:os.getcwd\n",
        "!!python/tuple [1, 2]\n",
    ],
)
def test_arbitrary_python_objects_stay_refused(text: str) -> None:
    with pytest.raises(yaml.YAMLError):
        load_yaml(text)


def test_uses_libyaml_when_the_build_has_it() -> None:
    # The whole point of the module: when the wheel ships libyaml, the C loader is
    # what runs. A source build without it legitimately falls back.
    if yaml.__with_libyaml__:
        assert SAFE_LOADER is yaml.CSafeLoader
    else:
        assert SAFE_LOADER is yaml.SafeLoader


def test_load_yaml_actually_runs_the_selected_engine() -> None:
    # The one place the two scanners visibly disagree on a plausible hand edit: a
    # stray tab after a value. libyaml reads it, the pure scanner refuses it. So
    # `load_yaml` reading it proves the C engine is what runs — a `load_yaml` that
    # quietly went back to `yaml.safe_load` would raise here. Without libyaml the
    # same document must be refused, so the test is meaningful on both builds.
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("a: b\t\n")
    if yaml.__with_libyaml__:
        assert load_yaml("a: b\t\n") == {"a": "b"}
    else:
        with pytest.raises(yaml.YAMLError):
            load_yaml("a: b\t\n")


def test_falls_back_to_the_pure_loader_without_libyaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(yaml, "__with_libyaml__", False)
    try:
        importlib.reload(yaml_io)
        assert yaml_io.SAFE_LOADER is yaml.SafeLoader
        assert yaml_io.load_yaml("a: 1\n") == {"a": 1}
    finally:
        monkeypatch.undo()
        importlib.reload(yaml_io)
    assert yaml_io.SAFE_LOADER is SAFE_LOADER


def test_every_backend_read_goes_through_the_one_loader() -> None:
    # One engine, one answer: a `yaml.safe_load(` creeping back in means the index
    # and a migration could disagree about whether a hand-edited file parses.
    app_root = Path(app.__file__).parent
    offenders = [
        str(path.relative_to(app_root))
        for path in app_root.rglob("*.py")
        if path.name != "yaml_io.py"
        and (
            "yaml.safe_load(" in path.read_text(encoding="utf-8")
            or "yaml.load(" in path.read_text(encoding="utf-8")
        )
    ]
    assert offenders == []
