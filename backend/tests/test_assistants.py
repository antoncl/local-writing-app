from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import UpdateProjectSettingsRequest
from app.runtime import service as global_service
from app.services import machine_settings as ms


class MigrateDefaultModelsTests(unittest.TestCase):
    """On first load after upgrade, the loader writes one assistant file per
    non-empty (provider, model) pair in default_models, then leaves them
    alone on subsequent loads."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_first_load_writes_one_file_per_pair(self) -> None:
        ms.load_settings()
        folder = self.config_dir / "assistants"
        files = sorted(p.name for p in folder.glob("*.md"))
        self.assertEqual(len(files), 4)  # one per DEFAULT_MODELS entry
        # The ★ is_default flag is retired (ADR-0024) — no file carries it; the
        # default_provider (ollama) assistant is instead seeded first so it is
        # the topmost (dynamic default) row.
        for p in folder.glob("*.md"):
            self.assertNotIn("is_default", p.read_text(encoding="utf-8"))

    def test_subsequent_load_is_a_no_op(self) -> None:
        ms.load_settings()
        # Sentinel file to prove migration won't re-run.
        sentinel = self.config_dir / "assistants" / "sentinel.md"
        sentinel.write_text("placeholder", encoding="utf-8")
        ms.load_settings()
        self.assertTrue(sentinel.exists())
        # No additional .md files appeared.
        self.assertEqual(len(list((self.config_dir / "assistants").glob("*.md"))), 5)

    def test_empty_default_models_writes_nothing(self) -> None:
        settings = ms.MachineSettings(default_models={})
        ms.save_settings(settings)
        ms.load_settings()
        self.assertFalse((self.config_dir / "assistants").exists())


class ProjectServiceResolveAssistantTests(unittest.TestCase):
    """ProjectService.resolve_assistant reads the file-backed index and
    returns the AssistantEntry whose id matches (or the topmost in roster
    order when no id is passed — the ★ is_default flag is retired, ADR-0024)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        folder = self.config_dir / "assistants"
        folder.mkdir(parents=True)
        (folder / "creative.md").write_text(
            "---\n"
            "id: creative\n"
            "title: Creative\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-sonnet-4-6\n"
            "  ai_temperature: 0.9\n"
            "  ai_max_tokens: 4096\n"
            "---\n",
            encoding="utf-8",
        )
        (folder / "cheap.md").write_text(
            "---\n"
            "id: cheap\n"
            "title: Cheap\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-haiku-4-5-20251001\n"
            "  ai_temperature: 0.2\n"
            "---\n",
            encoding="utf-8",
        )
        # These files are written directly rather than through
        # `create_assistant_entry`, which would have prepended each id to the
        # layer's `.order.yaml`. Seed the equivalent so the fixture matches an
        # install the app can actually produce: since #333 the dynamic default is
        # the first LISTED assistant, and a roster nothing has ever listed is a
        # test artifact, not a state a user reaches.
        (folder / ".order.yaml").write_text(
            "ids:\n- cheap\n- creative\nexcluded: []\n", encoding="utf-8"
        )
        global_service.__init__()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_resolve_by_id(self) -> None:
        result = global_service.resolve_assistant("cheap")
        assert result is not None
        self.assertEqual(result.id, "cheap")
        self.assertEqual(result.metadata["ai_model"], "claude-haiku-4-5-20251001")

    def test_resolve_falls_back_to_topmost(self) -> None:
        # No id → topmost in roster order. With no per-layer .order.yaml the
        # roster sorts by title, so "Cheap" precedes "Creative".
        result = global_service.resolve_assistant(None)
        assert result is not None
        self.assertEqual(result.id, "cheap")

    def test_resolve_returns_none_for_unknown_id(self) -> None:
        result = global_service.resolve_assistant("ghost")
        self.assertIsNone(result)


class ChatEndpointAssistantTests(unittest.TestCase):
    """Endpoint layer: assistant_id resolves to the assistant's params via
    the file-backed roster; explicit request fields still override."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Assistant Tests")
        global_service.update_project_settings(
            UpdateProjectSettingsRequest(ai_policy="cloud-allowed")
        )
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        folder = self.config_dir / "assistants"
        folder.mkdir(parents=True)
        (folder / "creative.md").write_text(
            "---\n"
            "id: creative\n"
            "title: Creative drafting\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-sonnet-4-6\n"
            "  ai_temperature: 0.9\n"
            "  ai_max_tokens: 2048\n"
            "---\n",
            encoding="utf-8",
        )
        (folder / "cheap.md").write_text(
            "---\n"
            "id: cheap\n"
            "title: Cheap summary\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-haiku-4-5-20251001\n"
            "  ai_temperature: 0.2\n"
            "  ai_max_tokens: 512\n"
            "---\n",
            encoding="utf-8",
        )
        # Written directly rather than through `create_assistant_entry`, which
        # would have listed each id — see ProjectServiceResolveAssistantTests.
        # The endpoint's no-id default is the first LISTED assistant since #333.
        (folder / ".order.yaml").write_text(
            "ids:\n- cheap\n- creative\nexcluded: []\n", encoding="utf-8"
        )
        # Seed machine settings with the api key.
        ms.save_settings(
            ms.MachineSettings(
                providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"),
                default_provider="anthropic",
                default_models={"anthropic": "claude-haiku-4-5-20251001"},
            )
        )

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_assistant_id_resolves_provider_model_temperature(self) -> None:
        with patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn", SimpleNamespace())) as mock:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "assistant_id": "creative",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = mock.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-sonnet-4-6")
        self.assertEqual(kwargs["temperature"], 0.9)
        self.assertEqual(kwargs["max_tokens"], 2048)

    def test_default_assistant_used_when_no_id_supplied(self) -> None:
        with patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn", SimpleNamespace())) as mock:
            response = self.client.post(
                "/api/ai/chat",
                json={"messages": [{"role": "user", "content": "Hi"}]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = mock.call_args.kwargs
        # No id → topmost by title ("Cheap summary" < "Creative drafting").
        self.assertEqual(kwargs["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(kwargs["temperature"], 0.2)

    def test_explicit_model_overrides_assistant(self) -> None:
        with patch("app.services.ai.providers._anthropic_chat", return_value=("ok", "end_turn", SimpleNamespace())) as mock:
            response = self.client.post(
                "/api/ai/chat",
                json={
                    "assistant_id": "creative",
                    "model": "claude-opus-4-8",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = mock.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-4-8")
        # Temperature still comes from the assistant — there's no override
        # field for it on the request shape (intentional; per-call temp tweaks
        # are a future enhancement).
        self.assertEqual(kwargs["temperature"], 0.9)


class MachineSettingsViewTests(unittest.TestCase):
    """The Slice D MachineSettingsView no longer exposes assistants or
    default_assistant_id — they moved entirely to the file-backed roster."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "View Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_get_does_not_expose_inline_assistants(self) -> None:
        body = self.client.get("/api/settings/machine").json()
        self.assertNotIn("assistants", body)
        self.assertNotIn("default_assistant_id", body)

    def test_put_ignores_legacy_assistants_payload(self) -> None:
        # The PUT silently drops unknown fields (FastAPI / Pydantic strict
        # validation would reject; the model declares only the kept fields).
        # We send a known-good provider patch alongside an obsolete assistants
        # payload and confirm the obsolete one has no effect.
        put = self.client.put(
            "/api/settings/machine",
            json={
                "default_provider": "anthropic",
                "assistants": [{"id": "x", "name": "X", "provider": "anthropic", "model": "m"}],
            },
        )
        self.assertEqual(put.status_code, 200, put.text)
        body = put.json()
        self.assertEqual(body["default_provider"], "anthropic")
        self.assertNotIn("assistants", body)


class FileBackedAssistantsTests(unittest.TestCase):
    """Slice A surface that survives Slice D: the file-backed assistants
    pane endpoint."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Files Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_assistant_index_includes_machine_layer(self) -> None:
        assistants_dir = self.config_dir / "assistants"
        assistants_dir.mkdir(parents=True)
        (assistants_dir / "fleet.md").write_text(
            "---\n"
            "id: fleet\n"
            "title: Fleet drafting\n"
            "entry_type: assistant\n"
            "metadata: { ai_provider: anthropic, ai_model: claude-sonnet-4-6 }\n"
            "---\n",
            encoding="utf-8",
        )
        response = self.client.get("/api/assistants")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        ids = [a["id"] for a in body["entries"]]
        self.assertIn("fleet", ids)
        fleet = next(a for a in body["entries"] if a["id"] == "fleet")
        self.assertEqual(fleet["source_layer_label"], "Machine")

    def test_create_assistant_endpoint_lands_in_machine_layer(self) -> None:
        create = self.client.post(
            "/api/assistants",
            json={"title": "New one", "entry_type": "assistant:assistant"},
        )
        self.assertEqual(create.status_code, 200, create.text)
        entry = create.json()
        self.assertTrue(entry["id"].startswith("assistant_"))
        self.assertEqual(entry["source_layer_label"], "Machine")
        files = list((self.config_dir / "assistants").glob("*.md"))
        self.assertEqual(len(files), 1)


class AssistantReorderTests(unittest.TestCase):
    """Slice C: per-layer assistants/.order.yaml drives list ordering;
    /api/assistants/order writes it."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Reorder Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        # Seed three machine-layer assistants.
        assistants_dir = self.config_dir / "assistants"
        assistants_dir.mkdir(parents=True)
        for slug in ("alpha", "bravo", "charlie"):
            (assistants_dir / f"{slug}.md").write_text(
                f"---\nid: {slug}\ntitle: {slug.capitalize()}\nentry_type: assistant\nmetadata: {{ ai_provider: anthropic, ai_model: m }}\n---\n",
                encoding="utf-8",
            )
        self.machine_layer_id = global_service._metadata_schema_layer_id(self.config_dir)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _assistant_file(self, entry_id: str) -> Path:
        """The assistant's file, resolved through the index rather than guessed.

        A save renames the file to match the title (`_maybe_rename_node_file`),
        and these fixtures deliberately write `alpha.md` with the title `Alpha`
        — so after any PUT the path is `Alpha.md`. On Windows the case-insensitive
        filesystem hides that and the old name still resolves; on Linux it does
        not. Hardcoding the name passed locally and failed in CI.
        """
        return global_service._build_assistant_index().by_id[entry_id].path

    def test_default_order_is_alphabetical(self) -> None:
        response = self.client.get("/api/assistants")
        ids = [e["id"] for e in response.json()["entries"]]
        self.assertEqual(ids, ["alpha", "bravo", "charlie"])

    def test_reorder_endpoint_writes_order_file(self) -> None:
        response = self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["charlie", "alpha"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        order_file = self.config_dir / "assistants" / ".order.yaml"
        self.assertTrue(order_file.exists())
        ids = [e["id"] for e in response.json()["entries"]]
        self.assertEqual(ids, ["charlie", "alpha", "bravo"])

    def test_reorder_with_unknown_id_returns_422(self) -> None:
        # Still 422, but on a narrower rule since #332: the id must exist
        # *somewhere in the roster*, not in this layer's own files. See
        # `test_reorder_accepts_an_inherited_id_and_writes_it_locally`.
        response = self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["alpha", "ghost"]},
        )
        self.assertEqual(response.status_code, 422)

    def test_creating_an_assistant_puts_it_on_top(self) -> None:
        # A new assistant leads its layer's list rather than landing in the
        # alphabetical tail — "Zulu" would otherwise sort last of four.
        #
        # The layer must ALREADY have a non-empty `ids` for this to test
        # prepend-vs-append at all: against an empty list the two are the same
        # operation, and the first version of this test passed against an
        # `append` mutant for exactly that reason.
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["alpha", "bravo"]},
        )
        response = self.client.post(
            "/api/assistants",
            json={"title": "Zulu", "entry_type": "assistant:assistant", "layer_id": ""},
        )
        self.assertEqual(response.status_code, 200, response.text)
        new_id = response.json()["id"]

        ids = [e["id"] for e in self.client.get("/api/assistants").json()["entries"]]
        self.assertEqual(ids, [new_id, "alpha", "bravo", "charlie"])

        # The FILE goes where asked — the machine layer, shared across projects.
        self.assertTrue((self.config_dir / "assistants" / "Zulu.md").exists())
        # The OPINION goes to the local layer (#333). These are different
        # questions, and conflating them is what used to make a new assistant
        # stop being the default: the fold puts local ids ahead of the inherited
        # remainder, so a machine-layer prepend sank below anything the project
        # had listed. Nothing is moved or copied to make a shared assistant lead.
        local_order = global_service._read_yaml(self.root / "assistants" / ".order.yaml")
        self.assertEqual(local_order["ids"], [new_id])
        machine_order = global_service._read_yaml(self.config_dir / "assistants" / ".order.yaml")
        self.assertEqual(machine_order["ids"], ["alpha", "bravo"], "the machine layer's opinion is untouched")

    def test_creating_an_assistant_leads_even_when_the_project_has_listed_others(self) -> None:
        # The regression the split caused: once the local layer holds ANY ids,
        # a machine-layer prepend lands the new assistant below every one of
        # them, so `resolve_assistant(None)` stops returning it.
        self.client.post("/api/assistants/order", json={"ordered_ids": ["charlie", "alpha", "bravo"]})
        response = self.client.post(
            "/api/assistants",
            json={"title": "Zulu", "entry_type": "assistant:assistant", "layer_id": ""},
        )
        new_id = response.json()["id"]
        ids = [e["id"] for e in self.client.get("/api/assistants").json()["entries"]]
        self.assertEqual(ids[0], new_id)
        self.assertEqual(global_service.resolve_assistant(None).id, new_id)

    def test_unlist_deactivates_an_assistant_without_hiding_it(self) -> None:
        # Seed a real `ids` first: against an empty list, unlist's "drop it from
        # `ids`" step is vacuous, and without it the merger's ids-wins rule
        # would keep the assistant listed and the unlist would silently do
        # nothing. The first version of this test missed that entirely.
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["bravo", "alpha"]},
        )
        response = self.client.post(
            "/api/assistants/unlist",
            json={"layer_id": self.machine_layer_id, "entry_id": "bravo"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        # `bravo` leaves the ACTIVE sequence and trails with the other unlisted
        # entry — it does not leave the roster. Nothing the app knows about may
        # become invisible, or the gesture has no undo (#333).
        entries = {e["id"]: e for e in response.json()["entries"]}
        self.assertEqual([e["id"] for e in response.json()["entries"]], ["alpha", "bravo", "charlie"])
        self.assertEqual(entries["alpha"]["computed_metadata"]["listed"], "listed")
        self.assertEqual(entries["bravo"]["computed_metadata"]["listed"], "unlisted")
        order = global_service._read_yaml(
            self.config_dir / "assistants" / ".order.yaml"
        )
        self.assertEqual(order["ids"], ["alpha"])
        self.assertEqual(order["excluded"], ["bravo"])
        # The assistant's own file is untouched — un-listing is an opinion held
        # by the layer, not a delete.
        self.assertTrue((self.config_dir / "assistants" / "bravo.md").exists())

    def test_unlist_then_reorder_relists(self) -> None:
        # A drag is a positive listing, so it outranks a stale exclusion at the
        # same layer; otherwise the drop would silently do nothing.
        self.client.post(
            "/api/assistants/unlist",
            json={"layer_id": self.machine_layer_id, "entry_id": "bravo"},
        )
        response = self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["bravo", "alpha"]},
        )
        self.assertEqual(
            [e["id"] for e in response.json()["entries"]], ["bravo", "alpha", "charlie"]
        )
        # The exclusion is cleared from the FILE, not merely out-voted by the
        # merger's ids-wins rule — otherwise we would persist a contradiction we
        # wrote ourselves, and log a warning about it on every read.
        order = global_service._read_yaml(self.config_dir / "assistants" / ".order.yaml")
        self.assertEqual(order["excluded"], [])

    def test_unlist_with_unknown_id_returns_422(self) -> None:
        response = self.client.post(
            "/api/assistants/unlist",
            json={"layer_id": self.machine_layer_id, "entry_id": "ghost"},
        )
        self.assertEqual(response.status_code, 422)

    def test_reorder_preserves_an_unrelated_exclusion(self) -> None:
        self.client.post(
            "/api/assistants/unlist",
            json={"layer_id": self.machine_layer_id, "entry_id": "charlie"},
        )
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["bravo", "alpha"]},
        )
        order = global_service._read_yaml(
            self.config_dir / "assistants" / ".order.yaml"
        )
        self.assertEqual(order["ids"], ["bravo", "alpha"])
        self.assertEqual(order["excluded"], ["charlie"])

    def test_subsequent_get_respects_saved_order(self) -> None:
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["bravo", "charlie", "alpha"]},
        )
        response = self.client.get("/api/assistants")
        ids = [e["id"] for e in response.json()["entries"]]
        self.assertEqual(ids, ["bravo", "charlie", "alpha"])

    def test_nothing_listed_stamps_every_entry_unlisted(self) -> None:
        # No layer holds an opinion, so the whole roster is the tail. Order is
        # still defined (alphabetical), which is exactly why `listed` cannot be
        # inferred from position.
        entries = self.client.get("/api/assistants").json()["entries"]
        curation = [e["computed_metadata"] for e in entries]
        self.assertEqual([c["listed"] for c in curation], ["unlisted"] * 3)
        self.assertEqual([c["position"] for c in curation], [None, None, None])

    def test_listing_stamps_listed_and_position(self) -> None:
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["charlie", "alpha"]},
        )
        entries = self.client.get("/api/assistants").json()["entries"]
        curation = {e["id"]: e["computed_metadata"] for e in entries}
        self.assertEqual(curation["charlie"], {"listed": "listed", "position": 0})
        self.assertEqual(curation["alpha"], {"listed": "listed", "position": 1})
        # `bravo` was never named, so it trails — unlisted, no position.
        self.assertEqual(curation["bravo"], {"listed": "unlisted", "position": None})

    def test_curation_is_never_written_into_stored_metadata(self) -> None:
        # The response keeping the pair out of `metadata` is the EASY half and
        # proves little on its own — the first version of this test asserted only
        # that and passed while the invariant was false. What has to hold is that
        # the pair cannot reach disk even when a client puts it there: a save
        # that froze a curation state into front matter would be contradicted by
        # the `.order.yaml` fold on the very next read.
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["alpha"]},
        )
        entry = next(e for e in self.client.get("/api/assistants").json()["entries"] if e["id"] == "alpha")
        self.assertNotIn("listed", entry["metadata"])
        self.assertNotIn("position", entry["metadata"])

        # A naive client spreading computed_metadata back into metadata on save.
        response = self.client.put(
            "/api/assistants/alpha",
            json={
                "title": "Alpha",
                "entry_type": "assistant:assistant",
                "metadata": {"tags": ["keep"], "listed": "unlisted", "position": 99},
                "base_revision": "",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        on_disk = self._assistant_file("alpha").read_text(encoding="utf-8")
        self.assertNotIn("listed", on_disk)
        self.assertNotIn("position", on_disk)
        # …and the strip is surgical: the stored field alongside them survives.
        self.assertIn("keep", on_disk)
        # The roster still reports the TRAVERSAL's answer, not the rejected one.
        entry = next(e for e in self.client.get("/api/assistants").json()["entries"] if e["id"] == "alpha")
        self.assertEqual(entry["computed_metadata"], {"listed": "listed", "position": 0})

    def test_unlisting_a_locally_owned_assistant_leaves_it_in_the_tail(self) -> None:
        # The case that used to orphan an assistant: its file lives at the very
        # layer doing the un-listing, so #332's roster filter dropped it out of
        # sight with no UI path back. Exclusion is now recorded exactly as it is
        # for an inherited id — the difference is that it no longer decides
        # visibility, so one uniform gesture covers both.
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["alpha", "bravo"]},
        )
        response = self.client.post(
            "/api/assistants/unlist",
            json={"layer_id": self.machine_layer_id, "entry_id": "alpha"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        entries = {e["id"]: e for e in response.json()["entries"]}
        self.assertIn("alpha", entries, "un-listing must not remove it from the roster")
        self.assertEqual(entries["alpha"]["computed_metadata"]["listed"], "unlisted")
        order = global_service._read_yaml(self.config_dir / "assistants" / ".order.yaml")
        self.assertEqual(order["ids"], ["bravo"])
        self.assertEqual(order["excluded"], ["alpha"])
        # …and it can be listed again, which is what makes the gesture safe.
        self.client.post("/api/assistants/order", json={"ordered_ids": ["alpha", "bravo"]})
        entries = {e["id"]: e for e in self.client.get("/api/assistants").json()["entries"]}
        self.assertEqual(entries["alpha"]["computed_metadata"]["listed"], "listed")

    def test_an_unlisted_assistant_is_never_the_default(self) -> None:
        # The roster shows un-listed entries since #333, so "topmost row" stopped
        # meaning "topmost of my roster". Without this, un-listing an assistant
        # while nothing else is listed made it the AI default — un-listing as a
        # way to START using something. Every AI call with no explicit
        # assistant_id resolves through here.
        self.client.post(
            "/api/assistants/unlist",
            json={"layer_id": self.machine_layer_id, "entry_id": "alpha"},
        )
        # `alpha` is still in the roster (visible, un-listed) and sorts first by
        # title, so the pre-#333 "topmost row" rule would hand it straight back.
        entries = [e["id"] for e in self.client.get("/api/assistants").json()["entries"]]
        self.assertEqual(entries[0], "alpha")
        # Nothing is listed, so there is no default — resolution never reaches
        # past the author's own list to pick something they did not choose.
        self.assertIsNone(global_service.resolve_assistant(None))

        # Listing one makes it the default; the un-listed `alpha` stays out even
        # though it still sorts first in the roster.
        self.client.post("/api/assistants/order", json={"ordered_ids": ["charlie"]})
        self.assertEqual(global_service.resolve_assistant(None).id, "charlie")

    def test_saving_an_assistant_keeps_fields_this_project_does_not_declare(self) -> None:
        # An assistant lives at the MACHINE layer and is shared by every project,
        # so a save must not filter its metadata against whichever project is
        # open. An earlier form of the curation guard ran the full
        # unknown/not-allowed strip here, which deleted any field another
        # project's schema layer declared: open project B, rename an assistant,
        # and project A's field was gone from disk for good.
        self.client.put(
            "/api/assistants/alpha",
            json={
                "title": "Alpha",
                "entry_type": "assistant:assistant",
                # `house_style` is declared by no schema this project can see.
                "metadata": {"tags": ["keep"], "house_style": "wry, close third"},
                "base_revision": "",
            },
        )
        on_disk = self._assistant_file("alpha").read_text(encoding="utf-8")
        self.assertIn("house_style", on_disk)
        self.assertIn("wry, close third", on_disk)

    def test_reading_one_assistant_stamps_curation_like_the_roster(self) -> None:
        # The editor opens a SINGLE entry, and for assistants the metadata rail
        # is the whole pane — so a computed field the roster fills and the single
        # read does not renders as a permanently blank locked row.
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["bravo", "alpha"]},
        )
        listed = self.client.get("/api/assistants/bravo").json()
        self.assertEqual(listed["computed_metadata"], {"listed": "listed", "position": 0})
        # …and the unlisted case reports the absence rather than omitting the key.
        unlisted = self.client.get("/api/assistants/charlie").json()
        self.assertEqual(unlisted["computed_metadata"], {"listed": "unlisted", "position": None})

    def test_unlisting_repositions_the_survivors(self) -> None:
        # Replaces an earlier test that asserted un-listing REMOVED the entry —
        # it was written against the orphan behaviour and codified it as intent.
        # What still has to hold is that positions renumber for whoever is left.
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["alpha", "bravo"]},
        )
        self.client.post(
            "/api/assistants/unlist",
            json={"layer_id": self.machine_layer_id, "entry_id": "alpha"},
        )
        curation = {e["id"]: e["computed_metadata"] for e in self.client.get("/api/assistants").json()["entries"]}
        self.assertEqual(curation["bravo"], {"listed": "listed", "position": 0})
        self.assertEqual(curation["alpha"], {"listed": "unlisted", "position": None})


class AssistantLayerOrderingTests(unittest.TestCase):
    """#332: the machine layer is the OUTERMOST layer, so it lands at the
    bottom of the merged priority sequence — most-local-wins, the rule the rest
    of the layer model already runs on.

    This inverts #224 / ADR-0037 §7, where layer rank led the sort key to keep
    the roster layer-grouped with the Machine bucket on top. That grouping was
    the thing making a project-specific assistant unable to become the default
    however the user ordered it, which is the defect #332 exists to remove; the
    `group_by: source_layer` default view that relied on it goes with #333."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        global_service.__init__()
        global_service.create_project(self.root, "Layer Order Tests")
        self.client = TestClient(app)
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        # A machine-layer assistant titled "Zed" — sorts LAST alphabetically,
        # so any cross-layer interleaving would drop it below a project "Alpha".
        machine_dir = self.config_dir / "assistants"
        machine_dir.mkdir(parents=True)
        (machine_dir / "zed.md").write_text(
            "---\nid: zed\ntitle: Zed\nentry_type: assistant\nmetadata: { ai_provider: anthropic, ai_model: m }\n---\n",
            encoding="utf-8",
        )
        self.machine_layer_id = global_service._metadata_schema_layer_id(self.config_dir)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_project_layer_sorts_before_machine_layer(self) -> None:
        # A project-layer assistant titled "Zeta", so it LOSES alphabetically to
        # the machine layer's "Zed" — the ordering below can then only come from
        # the layer merge, not from the title tiebreak.
        project_layer_id = global_service._metadata_schema_layer_id(self.root)
        project_dir = self.root / "assistants"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "zeta.md").write_text(
            "---\nid: zeta\ntitle: Zeta\nentry_type: assistant\nmetadata: { ai_provider: anthropic, ai_model: m }\n---\n",
            encoding="utf-8",
        )
        # Both listed, each at its own layer, so the merge — not the unlisted
        # alphabetical tail — decides.
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": project_layer_id, "ordered_ids": ["zeta"]},
        )
        self.client.post(
            "/api/assistants/order",
            json={"layer_id": self.machine_layer_id, "ordered_ids": ["zed"]},
        )

        entries = self.client.get("/api/assistants").json()["entries"]
        titles = [e["title"] for e in entries]
        labels = [e["source_layer_label"] for e in entries]
        # Project "Zeta" precedes machine "Zed". Pre-#332 this was ["Zed",
        # "Zeta"] because layer rank led the sort key and the machine layer
        # ranked 0 — which is exactly why a project assistant could never
        # become the default.
        self.assertEqual(titles, ["Zeta", "Zed"])
        self.assertNotEqual(labels[0], "Machine")
        self.assertEqual(labels[1], "Machine")

    def test_within_machine_layer_still_alphabetical(self) -> None:
        # Regression guard: the layer term must not disturb within-layer order.
        # A second machine assistant "Ada" still sorts before "Zed" (same layer).
        (self.config_dir / "assistants" / "ada.md").write_text(
            "---\nid: ada\ntitle: Ada\nentry_type: assistant\nmetadata: { ai_provider: anthropic, ai_model: m }\n---\n",
            encoding="utf-8",
        )
        titles = [e["title"] for e in self.client.get("/api/assistants").json()["entries"]]
        self.assertEqual(titles, ["Ada", "Zed"])


if __name__ == "__main__":
    unittest.main()
