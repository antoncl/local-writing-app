"""`{% include %}` inclusion is a reference edge (ADR-0061 §5).

A prompt that pulls in a `prompt:snippet` with a literal `{% include %}` records
an `INCLUDE_FIELD_ID` reference edge in the node index, so *"what includes this
snippet?"* is a reverse-index lookup — the data the editor's dependency alert
(S3) rides on. The edge target is resolved with the *same* `match_snippet_name`
the render loader and the S1 effective-inputs resolver use, so an edge points at
the snippet that actually renders (no gather/render/dependency drift).

Because resolving an include name needs the complete snippet set, the edge is
extracted in a whole-index finalize (`_extract_include_edges`) after the walk,
not per-file like the `entity_ref` edges — these tests pin that it lands in the
same forward/reverse maps and survives the snapshot round-trip regardless.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_fixtures import open_test_project

from app.models import (
    CreateChatSessionRequest,
    CreatePromptEntryRequest,
    MetadataFieldDefinition,
    PromptInputDefinition,
    SavePromptEntryRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project.node_index import ReferenceEdge
from app.services.project.node_index_gate import node_index_gate
from app.services.project.references import INCLUDE_FIELD_ID


class IncludeEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Include Edge Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _save_prompt(
        self,
        title: str,
        body: str,
        entry_type: str,
        inputs: list[PromptInputDefinition] | None = None,
    ) -> str:
        entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title=title, entry_type=entry_type)
        )
        self.service.save_prompt_entry(
            entry.id,
            SavePromptEntryRequest(
                title=title,
                body=body,
                base_revision=entry.revision,
                entry_type=entry_type,
                metadata={},
                inputs=inputs or [],
            ),
        )
        return entry.id

    def test_include_is_a_reference_edge(self) -> None:
        snippet = self._save_prompt("Villain Voice", "{{ input.menace }}", "prompt:snippet")
        prompt = self._save_prompt(
            "Revise Scene", '{% include "Villain Voice" %}', "prompt:general"
        )

        index = self.service._build_node_index()
        self.assertEqual(
            index.edges_by_src[prompt],
            [ReferenceEdge(src=prompt, dst=snippet, field_id=INCLUDE_FIELD_ID)],
        )
        # The snippet includes nothing → absent as a source.
        self.assertNotIn(snippet, index.edges_by_src)

    def test_reverse_index_lists_every_includer(self) -> None:
        snippet = self._save_prompt("Villain Voice", "{{ input.menace }}", "prompt:snippet")
        first = self._save_prompt("Revise", '{% include "Villain Voice" %}', "prompt:general")
        second = self._save_prompt("Draft", '{% include "Villain Voice" %}', "prompt:general")

        index = self.service._build_node_index()
        # Sorted by (src, field_id) like every reverse-edge list — so assert on a set.
        self.assertEqual(
            {(e.src, e.field_id) for e in index.edges_by_dst[snippet]},
            {(first, INCLUDE_FIELD_ID), (second, INCLUDE_FIELD_ID)},
        )

    def test_include_by_id_resolves(self) -> None:
        # id-first matching: an include naming the snippet's id resolves even
        # when it does not match the title.
        snippet = self._save_prompt("Villain Voice", "{{ input.menace }}", "prompt:snippet")
        prompt = self._save_prompt(
            "Revise", f'{{% include "{snippet}" %}}', "prompt:general"
        )

        index = self.service._build_node_index()
        self.assertEqual(
            index.edges_by_dst[snippet],
            [ReferenceEdge(src=prompt, dst=snippet, field_id=INCLUDE_FIELD_ID)],
        )

    def test_dangling_include_yields_no_edge(self) -> None:
        # An include naming nothing that exists contributes no edge and does not
        # raise — mirrors the render loader's TemplateNotFound tolerance.
        self._save_prompt("Villain Voice", "{{ input.menace }}", "prompt:snippet")
        prompt = self._save_prompt(
            "Revise", '{% include "No Such Snippet" %}', "prompt:general"
        )

        index = self.service._build_node_index()
        self.assertNotIn(prompt, index.edges_by_src)

    def test_ambiguous_title_yields_no_edge(self) -> None:
        # Two snippets share a title → a title-based include is ambiguous, so it
        # resolves to nothing (same rule as the loader), and no edge is recorded.
        self._save_prompt("Shared", "{{ input.a }}", "prompt:snippet")
        self._save_prompt("Shared", "{{ input.b }}", "prompt:snippet")
        prompt = self._save_prompt("Revise", '{% include "Shared" %}', "prompt:general")

        index = self.service._build_node_index()
        self.assertNotIn(prompt, index.edges_by_src)

    def test_including_a_non_snippet_prompt_yields_no_edge(self) -> None:
        # Only `prompt:snippet` entries are include targets — a name matching an
        # ordinary prompt is not a snippet, so it contributes no edge (the loader
        # filters to snippets too).
        self._save_prompt("Ordinary", "{{ input.x }}", "prompt:general")
        prompt = self._save_prompt("Revise", '{% include "Ordinary" %}', "prompt:general")

        index = self.service._build_node_index()
        self.assertNotIn(prompt, index.edges_by_src)

    def test_duplicate_include_is_one_edge(self) -> None:
        # The same snippet included twice is one edge — deduped within the source,
        # like a repeated entity_ref target.
        snippet = self._save_prompt("Villain Voice", "{{ input.menace }}", "prompt:snippet")
        prompt = self._save_prompt(
            "Revise",
            '{% include "Villain Voice" %}\n{% include "Villain Voice" %}',
            "prompt:general",
        )

        index = self.service._build_node_index()
        self.assertEqual(
            index.edges_by_src[prompt],
            [ReferenceEdge(src=prompt, dst=snippet, field_id=INCLUDE_FIELD_ID)],
        )

    def test_transitive_include_is_a_direct_edge_per_hop(self) -> None:
        # A → B → C records A→B and B→C, not a synthetic A→C: the edge graph is
        # the literal include relation; transitivity is the effective-inputs
        # resolver's concern, not the reference graph's.
        inner = self._save_prompt("Inner", "{{ input.c }}", "prompt:snippet")
        middle = self._save_prompt("Middle", '{% include "Inner" %}', "prompt:snippet")
        outer = self._save_prompt("Outer", '{% include "Middle" %}', "prompt:general")

        index = self.service._build_node_index()
        self.assertEqual(
            index.edges_by_src[outer],
            [ReferenceEdge(src=outer, dst=middle, field_id=INCLUDE_FIELD_ID)],
        )
        self.assertEqual(
            index.edges_by_src[middle],
            [ReferenceEdge(src=middle, dst=inner, field_id=INCLUDE_FIELD_ID)],
        )

    def test_include_and_entity_ref_edges_coexist_on_one_prompt(self) -> None:
        # A prompt can carry both an `entity_ref` field edge (from the per-file
        # walk) and an include edge (from the finalize). The finalize *appends*
        # to `edges_by_layer_src`, so both survive — field edge first, in
        # field-declaration order, then the include.
        layers = self.service.read_metadata_schema_layers()
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layers.layers[-1].id,
                field_id="related_prompt",
                field=MetadataFieldDefinition(name="Related Prompt", type="entity_ref"),
                entry_type="prompt:general",
            )
        )
        snippet = self._save_prompt("Villain Voice", "{{ input.menace }}", "prompt:snippet")
        target = self._save_prompt("Target", "{{ input.x }}", "prompt:general")
        prompt = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title="Revise", entry_type="prompt:general")
        ).id
        entry = self.service.read_prompt_entry(prompt)
        self.service.save_prompt_entry(
            prompt,
            SavePromptEntryRequest(
                title="Revise",
                body='{% include "Villain Voice" %}',
                base_revision=entry.revision,
                entry_type="prompt:general",
                metadata={"related_prompt": target},
                inputs=[],
            ),
        )

        index = self.service._build_node_index()
        self.assertEqual(
            index.edges_by_src[prompt],
            [
                ReferenceEdge(src=prompt, dst=target, field_id="related_prompt"),
                ReferenceEdge(src=prompt, dst=snippet, field_id=INCLUDE_FIELD_ID),
            ],
        )

    def test_include_edges_are_absent_from_the_entity_ref_reference_graph(self) -> None:
        # `reference_graph()` is the entity-ref references view (the frontend
        # inverts it for the `references` computed field). An include is a
        # template-composition edge with its own dependency surface (S3), not an
        # `entity_ref`, so it must not leak into it — a prompt whose only edge is
        # an include is absent as a key.
        self._save_prompt("Villain Voice", "{{ input.menace }}", "prompt:snippet")
        prompt = self._save_prompt(
            "Revise", '{% include "Villain Voice" %}', "prompt:general"
        )

        self.assertNotIn(prompt, self.service.reference_graph().refs)

    def test_include_edges_survive_the_snapshot_round_trip(self) -> None:
        # The finalize appends to `edges_by_layer_src`, which the snapshot
        # serializes generically — so a warm open served from the snapshot carries
        # the include edge without any include-specific persistence code.
        snippet = self._save_prompt("Villain Voice", "{{ input.menace }}", "prompt:snippet")
        prompt = self._save_prompt(
            "Revise", '{% include "Villain Voice" %}', "prompt:general"
        )

        # First build writes the snapshot; dropping the in-memory memo forces the
        # next build to rehydrate from disk rather than reuse the built index.
        self.service._build_node_index()
        node_index_gate.invalidate()
        index = self.service._build_node_index()
        self.assertEqual(
            index.edges_by_dst[snippet],
            [ReferenceEdge(src=prompt, dst=snippet, field_id=INCLUDE_FIELD_ID)],
        )


class SnippetDependentsTests(unittest.TestCase):
    """The "used by N prompts / M chats" counts (ADR-0061 S3a)."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Snippet Dependents Tests")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _save_prompt(self, title: str, body: str, entry_type: str) -> str:
        entry = self.service.create_prompt_entry(
            CreatePromptEntryRequest(title=title, entry_type=entry_type)
        )
        self.service.save_prompt_entry(
            entry.id,
            SavePromptEntryRequest(
                title=title, body=body, base_revision=entry.revision,
                entry_type=entry_type, metadata={}, inputs=[],
            ),
        )
        return entry.id

    def test_prompt_count_is_the_transitive_include_closure(self) -> None:
        voice = self._save_prompt("Voice", "{{ input.m }}", "prompt:snippet")
        mid = self._save_prompt("Mid", '{% include "Voice" %}', "prompt:snippet")
        direct = self._save_prompt("Direct", '{% include "Voice" %}', "prompt:general")
        nested = self._save_prompt("Nested", '{% include "Mid" %}', "prompt:general")
        self._save_prompt("Unrelated", "{{ input.x }}", "prompt:general")

        # direct + mid include Voice; nested includes Mid, so depends transitively.
        self.assertEqual(self.service.prompts_including_snippet(voice), {mid, direct, nested})
        dep = self.service.snippet_dependents(voice)
        self.assertEqual((dep.prompt_count, dep.chat_count), (3, 0))

    def test_chat_count_counts_chats_locked_to_an_including_prompt(self) -> None:
        voice = self._save_prompt("Voice", "{{ input.m }}", "prompt:snippet")
        including = self._save_prompt("Revise", '{% include "Voice" %}', "prompt:general")
        other = self._save_prompt("Other", "{{ input.x }}", "prompt:general")
        self.service.create_chat_session(CreateChatSessionRequest(title="c1", prompt_entry_id=including))
        self.service.create_chat_session(CreateChatSessionRequest(title="c2", prompt_entry_id=including))
        self.service.create_chat_session(CreateChatSessionRequest(title="c3", prompt_entry_id=other))
        self.service.create_chat_session(CreateChatSessionRequest(title="c4"))  # freeform, no prompt

        dep = self.service.snippet_dependents(voice)
        self.assertEqual((dep.prompt_count, dep.chat_count), (1, 2))

    def test_a_snippet_nothing_includes_has_no_dependents(self) -> None:
        lonely = self._save_prompt("Lonely", "{{ input.m }}", "prompt:snippet")
        dep = self.service.snippet_dependents(lonely)
        self.assertEqual((dep.prompt_count, dep.chat_count), (0, 0))

    def test_an_include_cycle_terminates_and_excludes_the_snippet_itself(self) -> None:
        # A includes B, B includes A. Neither is its own dependent, and the walk
        # terminates rather than looping.
        a = self._save_prompt("A", '{% include "B" %}', "prompt:snippet")
        b = self._save_prompt("B", '{% include "A" %}', "prompt:snippet")

        self.assertEqual(self.service.prompts_including_snippet(a), {b})
        self.assertEqual(self.service.prompts_including_snippet(b), {a})


if __name__ == "__main__":
    unittest.main()
