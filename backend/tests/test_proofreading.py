"""Proofreading files and endpoints (ADR-0102 §4–§7, slice 2).

`proofreading.yaml` per layer (words, rules, dialect) merges down the chain —
Library fiction default, machine, then the projects outermost first, nearer
winning; `proofreading.ignored.yaml` keeps ignore-here hashes per node in the
project the node lives in. Both optional: a project with neither reads empty.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import bind_test_project

from app.main import app
from app.models import (
    CreateSceneRequest,
    ProofreadingDialectRequest,
    ProofreadingIgnoreRequest,
    ProofreadingRuleRequest,
    ProofreadingWordRequest,
)
from app.scope import WorkScope
from app.services import machine_settings as ms_service
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class ProofreadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.world = self.base / "honorverse"
        self.series = self.world / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        declare_full_chain(ProjectService(WorkScope(root=self.series)), self.series, self.base)
        bind_test_project(self.service)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _layer(self, *, folder: Path | None = None, machine: bool = False, library: bool = False) -> str:
        setup = self.service.read_proofreading()
        if machine or library:
            return next(x.id for x in setup.layers if (x.is_machine if machine else x.is_library))
        layer = next(x for x in self.service.collect_layers(self.root) if x.folder == folder)
        return layer.id

    def _file(self, folder: Path, name: str = "proofreading.yaml") -> dict:
        return yaml.safe_load((folder / name).read_text(encoding="utf-8"))

    # ---------- reading ----------

    def test_absent_files_read_as_the_fiction_default_only(self) -> None:
        setup = self.service.read_proofreading()
        self.assertEqual(setup.words, [])
        self.assertEqual(setup.ignored, {})
        self.assertEqual(setup.dialect, "american")
        # The shipped Library file switches the fiction-hostile rules off.
        self.assertIs(setup.rules["OxfordComma"], False)
        library = next(x for x in setup.layers if x.is_library)
        self.assertEqual(setup.rule_layers["OxfordComma"], library.id)
        self.assertFalse((self.root / "proofreading.yaml").exists())

    def test_layers_are_library_machine_then_the_chain_outermost_first(self) -> None:
        setup = self.service.read_proofreading()
        self.assertTrue(setup.layers[0].is_library)
        # The machine is a target before it holds anything.
        self.assertTrue(setup.layers[1].is_machine)
        chain = [x.id for x in self.service.collect_layers(self.root)]
        self.assertEqual([x.id for x in setup.layers[2:]], chain)
        self.assertTrue(setup.layers[-1].is_root)

    def test_words_are_the_union_and_a_world_word_reaches_the_book(self) -> None:
        self.service.add_proofreading_word(ProofreadingWordRequest(word="skyglass", layer_id=self._layer(folder=self.world)))
        setup = self.service.add_proofreading_word(ProofreadingWordRequest(word="Vashti", layer_id=self._layer(folder=self.root)))
        self.assertEqual(setup.words, ["Vashti", "skyglass"])
        self.assertEqual(setup.word_layers["skyglass"], [self._layer(folder=self.world)])
        self.assertEqual(self._file(self.world), {"words": ["skyglass"]})

    def test_a_nearer_layer_wins_a_rule_and_the_dialect(self) -> None:
        self.service.set_proofreading_rule(
            ProofreadingRuleRequest(rule="OxfordComma", enabled=True, layer_id=self._layer(machine=True))
        )
        self.assertIs(self.service.read_proofreading().rules["OxfordComma"], True)
        self.service.set_proofreading_rule(
            ProofreadingRuleRequest(rule="OxfordComma", enabled=False, layer_id=self._layer(folder=self.root))
        )
        self.service.set_proofreading_dialect(ProofreadingDialectRequest(dialect="british", layer_id=self._layer(folder=self.world)))
        setup = self.service.read_proofreading()
        self.assertIs(setup.rules["OxfordComma"], False)
        self.assertEqual(setup.rule_layers["OxfordComma"], self._layer(folder=self.root))
        self.assertEqual(setup.dialect, "british")

    def test_setting_a_rule_back_to_inherited_removes_the_key(self) -> None:
        layer = self._layer(folder=self.root)
        self.service.set_proofreading_rule(ProofreadingRuleRequest(rule="SpellCheck", enabled=False, layer_id=layer))
        setup = self.service.set_proofreading_rule(ProofreadingRuleRequest(rule="SpellCheck", enabled=None, layer_id=layer))
        self.assertNotIn("SpellCheck", setup.rules)
        self.assertNotIn("rules", self._file(self.root))

    def test_an_unknown_rule_name_on_disk_is_kept(self) -> None:
        (self.root / "proofreading.yaml").write_text("rules:\n  RetiredRule: false\n", encoding="utf-8")
        self.service.set_proofreading_rule(
            ProofreadingRuleRequest(rule="Hedging", enabled=True, layer_id=self._layer(folder=self.root))
        )
        self.assertEqual(self._file(self.root)["rules"], {"Hedging": True, "RetiredRule": False})

    # ---------- the machine layer ----------

    def test_a_machine_word_makes_the_machine_a_layer_of_the_walk(self) -> None:
        machine_dir = ms_service.assistants_dir().parent
        self.assertIsNone(self.service.machine_layer())
        self.service.add_proofreading_word(ProofreadingWordRequest(word="Grayson", layer_id=self._layer(machine=True)))
        self.assertEqual(self._file(machine_dir), {"words": ["Grayson"]})
        self.assertIsNotNone(self.service.machine_layer())
        self.assertIn("Grayson", self.service.read_proofreading().words)
        # The node index reads that machine layer as empty, not as an error.
        self.service._build_node_index(self.root)

    # ---------- refusals ----------

    def test_the_library_is_read_only(self) -> None:
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.add_proofreading_word(ProofreadingWordRequest(word="x", layer_id=self._layer(library=True)))
        self.assertEqual(caught.exception.status_code, 409)

    def test_an_unknown_layer_is_404(self) -> None:
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.add_proofreading_word(ProofreadingWordRequest(word="x", layer_id="nope"))
        self.assertEqual(caught.exception.status_code, 404)

    def test_a_word_with_a_space_is_refused(self) -> None:
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.add_proofreading_word(ProofreadingWordRequest(word="two words", layer_id=self._layer(folder=self.root)))
        self.assertEqual(caught.exception.status_code, 422)

    # ---------- ignore here ----------

    def test_ignore_here_is_saved_by_node_and_drops_deleted_nodes(self) -> None:
        scene = self.service.create_scene(CreateSceneRequest(title="Opening"))
        (self.root / "proofreading.ignored.yaml").write_text(
            "ignored:\n  manuscript_gone:\n    - '1'\n", encoding="utf-8"
        )
        setup = self.service.ignore_proofreading_spot(ProofreadingIgnoreRequest(node_id=scene.id, hash="18446744073709551615"))
        self.assertEqual(setup.ignored, {scene.id: ["18446744073709551615"]})
        self.assertEqual(self._file(self.root, "proofreading.ignored.yaml"), {"ignored": {scene.id: ["18446744073709551615"]}})
        # The same spot twice is one entry.
        setup = self.service.ignore_proofreading_spot(ProofreadingIgnoreRequest(node_id=scene.id, hash="18446744073709551615"))
        self.assertEqual(setup.ignored[scene.id], ["18446744073709551615"])

    def test_ignore_here_refuses_an_unknown_node_and_an_oversized_hash(self) -> None:
        scene = self.service.create_scene(CreateSceneRequest(title="Opening"))
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.ignore_proofreading_spot(ProofreadingIgnoreRequest(node_id="manuscript_nope", hash="1"))
        self.assertEqual(caught.exception.status_code, 404)
        with self.assertRaises(ProjectServiceError) as caught:
            self.service.ignore_proofreading_spot(ProofreadingIgnoreRequest(node_id=scene.id, hash="18446744073709551616"))
        self.assertEqual(caught.exception.status_code, 422)

    # ---------- over the wire ----------

    def test_routes_round_trip(self) -> None:
        layer = self._layer(folder=self.root)
        response = self.client.post("/api/proofreading/words", json={"word": "Vashti", "layer_id": layer})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["words"], ["Vashti"])
        response = self.client.post("/api/proofreading/words/remove", json={"word": "Vashti", "layer_id": layer})
        self.assertEqual(response.json()["words"], [])
        response = self.client.put("/api/proofreading/rules", json={"rule": "LongSentences", "enabled": False, "layer_id": layer})
        self.assertIs(response.json()["rules"]["LongSentences"], False)
        response = self.client.put("/api/proofreading/dialect", json={"dialect": "canadian", "layer_id": layer})
        self.assertEqual(response.json()["dialect"], "canadian")
        self.assertEqual(self.client.get("/api/proofreading").json()["dialect"], "canadian")
        # A malformed rule name or hash is the request's fault.
        bad = self.client.put("/api/proofreading/rules", json={"rule": "not a rule", "enabled": False, "layer_id": layer})
        self.assertEqual(bad.status_code, 422)
        bad = self.client.post("/api/proofreading/ignores", json={"node_id": "x", "hash": "-1"})
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
