from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import SavePromptEntryRequest
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class BuiltinPromptEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = ProjectService.created_at(self.root, "Prompt Builtins")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_project_creation_seeds_readonly_plot_prompts(self) -> None:
        listing = {entry.id: entry for entry in self.service.list_prompt_entries().entries}

        brainstorm = listing["prompt_builtin_plot_brainstorm"]
        audit = listing["prompt_builtin_plot_claim_audit"]
        self.assertEqual(brainstorm.entry_type, "prompt:general")
        self.assertEqual(audit.entry_type, "prompt:general")
        self.assertTrue(brainstorm.system)
        self.assertTrue(audit.system)
        self.assertEqual([item.name for item in brainstorm.inputs], ["plot", "focus"])
        self.assertEqual([item.name for item in audit.inputs], ["plot", "focus"])
        self.assertIn("context_xml(plot_context(input.plot))", brainstorm.body)
        self.assertIn("<plot_suggestions>", brainstorm.body)
        self.assertIn("<plot_review", audit.body)
        self.assertIn("<plot_suggestions>", audit.body)

        read_back = self.service.read_prompt_entry("prompt_builtin_plot_brainstorm")
        self.assertTrue(read_back.system)
        self.assertEqual(read_back.entry_type, "prompt:general")

    def test_open_project_refreshes_sparse_system_builtin_prompt(self) -> None:
        self.service._write_node_entry_file(
            self.root / "prompts" / "Plot Brainstorm.md",
            "prompt_builtin_plot_brainstorm",
            "Plot Brainstorm",
            "prompt:general",
            {},
            "old body",
            extra={"system": True},
            omit_empty_metadata=True,
        )

        reopened = ProjectService.opened_at(self.root)
        prompt = reopened.read_prompt_entry("prompt_builtin_plot_brainstorm")

        self.assertTrue(prompt.system)
        self.assertEqual([item.name for item in prompt.inputs], ["plot", "focus"])
        self.assertIn("context_xml(plot_context(input.plot))", prompt.body)
        self.assertNotEqual(prompt.body, "old body")

    def test_layered_builtin_prompt_shadows_are_silent(self) -> None:
        base = Path(self.temp_dir.name).resolve() / "writing"
        universe = base / "honorverse"
        book = universe / "book01"
        service = ProjectService.created_at(book, "Book 1")
        declare_full_chain(service, book, base)

        ProjectService.created_at(universe, "Honorverse")
        reopened = ProjectService.opened_at(book)
        index = reopened._build_node_index(book)

        for node_id in ("prompt_builtin_plot_brainstorm", "prompt_builtin_plot_claim_audit"):
            self.assertEqual(len(index.candidates[node_id]), 2)
        self.assertEqual([warning for warning in index.warnings if "prompt_builtin" in warning], [])

    def test_local_system_builtin_refreshes_even_when_ancestor_has_same_prompt(self) -> None:
        base = Path(self.temp_dir.name).resolve() / "writing"
        universe = base / "honorverse"
        book = universe / "book01"
        service = ProjectService.created_at(book, "Book 1")
        declare_full_chain(service, book, base)
        service._write_node_entry_file(
            book / "prompts" / "Plot Brainstorm.md",
            "prompt_builtin_plot_brainstorm",
            "Plot Brainstorm",
            "prompt:general",
            {},
            "old child body",
            extra={"system": True},
            omit_empty_metadata=True,
        )

        ProjectService.created_at(universe, "Honorverse")
        reopened = ProjectService.opened_at(book)
        prompt = reopened.read_prompt_entry("prompt_builtin_plot_brainstorm")

        self.assertEqual(prompt.source_layer_label, "Book 1")
        self.assertIn("context_xml(plot_context(input.plot))", prompt.body)
        self.assertNotEqual(prompt.body, "old child body")

    def test_system_prompt_rejects_save_and_delete(self) -> None:
        prompt = self.service.read_prompt_entry("prompt_builtin_plot_claim_audit")
        with self.assertRaises(ProjectServiceError) as save_error:
            self.service.save_prompt_entry(
                prompt.id,
                SavePromptEntryRequest(
                    title=prompt.title,
                    body="changed",
                    base_revision=prompt.revision,
                    entry_type=prompt.entry_type,
                    metadata=prompt.metadata,
                    inputs=prompt.inputs,
                ),
            )
        self.assertEqual(save_error.exception.status_code, 403)

        with self.assertRaises(ProjectServiceError) as delete_error:
            self.service.delete_prompt_entry(prompt.id)
        self.assertEqual(delete_error.exception.status_code, 403)
