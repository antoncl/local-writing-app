"""The resolved-definitions cache (#394).

Design of record: `docs/design/resolved-definitions-cache.md`. These are the
behavioural contract from that doc's "The tests it must pass" section — each
grouped by the principle it defends and named with the mutation it catches, so a
test whose regression cannot be named is not here.

The chain is the four layers the as-of-L and tag suites use:
`writing (base) → honorverse → honor-harrington → book01 (root)`.

The two caches are process-global, so `setUp` clears them (and the node-index
gate) — in production they live and die with the process (§ no eviction), but
tests share one interpreter.
"""

from __future__ import annotations

import os
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from layer_fixtures import declare_full_chain, make_project_folder

from app.services.project import schema_cache
from app.services.project.node_index_gate import node_index_gate
from app.services.project_service import ProjectService


class SchemaCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: Windows hands back the 8.3 short form while the walk
        # canonicalises (#356), and the cache keys on the resolved path.
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        schema_cache.clear()
        node_index_gate.invalidate()

    def tearDown(self) -> None:
        schema_cache.clear()
        node_index_gate.invalidate()
        self.temp_dir.cleanup()

    # --- helpers -------------------------------------------------------

    def _layer_id(self, folder: Path) -> str:
        return next(
            layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder
        )

    def _write_field_at(self, folder: Path, field: str) -> None:
        """Define one text field on `lore:character` at a layer, replacing any
        schema already there (so a second call is a *content change*)."""
        make_project_folder(self.service, folder)
        self.service._write_yaml(
            folder / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {field: {"name": field, "type": "text", "label": field.title()}},
                "entry_types": {"lore:character": {"fields": [field]}},
            },
        )

    def _delete_schema_at(self, folder: Path) -> None:
        (folder / "metadata.schema.yaml").unlink()

    @contextmanager
    def _parse_spy(self) -> Iterator[mock.Mock]:
        """Count YAML parses by wrapping the layer reader the cache calls on a
        miss. `call_args_list[i].args[0]` is the path parsed."""
        original = self.service._read_metadata_schema_layer
        with mock.patch.object(
            self.service, "_read_metadata_schema_layer", wraps=original
        ) as spy:
            yield spy

    def _parsed_paths(self, spy: mock.Mock) -> list[Path]:
        return [call.args[0] for call in spy.call_args_list]

    # --- A. the parse is cached ----------------------------------------

    def test_second_read_of_an_unchanged_chain_parses_no_yaml(self) -> None:
        # Catches: a cache that stores but never hits.
        self._write_field_at(self.root, "alpha")
        with self._parse_spy() as spy:
            self.service.read_metadata_schema()
            after_first = spy.call_count
            self.assertGreaterEqual(after_first, 1)
            self.service.read_metadata_schema()
            self.assertEqual(spy.call_count, after_first)

    def test_a_shared_ancestor_is_parsed_once_across_two_chains(self) -> None:
        # Catches: collapsing the per-layer atom into a per-chain cache, which
        # re-parses shared ancestors once per descendant.
        book02 = self.series / "book02"
        declare_full_chain(self.service, book02, self.base)
        self._write_field_at(self.series, "shared")  # only the shared ancestor has a schema
        schema_cache.clear()

        with self._parse_spy() as spy:
            self.service.read_metadata_schema(self.root)
            self.assertIn(self.series / "metadata.schema.yaml", self._parsed_paths(spy))
            spy.reset_mock()
            self.service.read_metadata_schema(book02)
            self.assertEqual(self._parsed_paths(spy), [])

    # --- B. invalidation is per-layer ----------------------------------

    def test_editing_one_layer_reparses_only_that_layer(self) -> None:
        # Catches: whole-chain invalidation — the fusion this design breaks.
        self._write_field_at(self.series, "seriesfield")
        self._write_field_at(self.root, "bookfield")
        self.service.read_metadata_schema()  # warm both atoms

        with self._parse_spy() as spy:
            self._write_field_at(self.root, "bookfield2")  # edit the book only
            self.service.read_metadata_schema()
            self.assertEqual(
                self._parsed_paths(spy), [self.root / "metadata.schema.yaml"]
            )

    # --- C. the merged result ------------------------------------------

    def test_two_reads_of_an_unchanged_chain_return_the_same_object(self) -> None:
        # Catches: caching only the parse and leaving the merge to churn — this
        # goes red if the merged (level-2) cache is dropped.
        self._write_field_at(self.root, "alpha")
        first = self.service.read_metadata_schema()
        second = self.service.read_metadata_schema()
        self.assertIs(first, second)

    def test_a_build_identity_change_rebuilds_the_merged_result(self) -> None:
        # Catches: code identity missing from the merged key — a model change
        # silently serving stale validated objects.
        self._write_field_at(self.root, "alpha")
        first = self.service.read_metadata_schema()
        with mock.patch.object(schema_cache, "build_identity", return_value="different-build"):
            rebuilt = self.service.read_metadata_schema()
        self.assertIsNot(rebuilt, first)
        self.assertEqual(set(rebuilt.fields), set(first.fields))  # same inputs, same content

    def test_a_build_identity_change_reparses_no_atom(self) -> None:
        # Catches: code identity leaking into the atom key, killing cross-project
        # reuse. The adversarial dual of the test above.
        self._write_field_at(self.root, "alpha")
        self.service.read_metadata_schema()  # warm the atom
        with self._parse_spy() as spy, mock.patch.object(
            schema_cache, "build_identity", return_value="different-build"
        ):
            self.service.read_metadata_schema()
            self.assertEqual(spy.call_count, 0)

    # --- D. as-of-L is a truncated fold --------------------------------

    def test_as_of_root_equals_the_full_read(self) -> None:
        # Catches: an as-of-L path that merges differently from the full path.
        self._write_field_at(self.root, "bookfield")
        full = self.service.read_metadata_schema()
        as_of_root = self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.root))
        self.assertEqual(set(as_of_root.fields), set(full.fields))

    def test_a_definition_below_L_does_not_leak_into_the_as_of_L_result(self) -> None:
        # Catches: truncation implemented as a filter that leaks lower layers —
        # or a merged key that fails to distinguish L from the full chain.
        self._write_field_at(self.root, "bookfield")
        as_of_series = self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.series))
        self.assertNotIn("bookfield", as_of_series.fields)
        # And the full read, cached under a different key, still sees it.
        self.assertIn("bookfield", self.service.read_metadata_schema().fields)

    def test_as_of_L_parses_no_additional_files(self) -> None:
        # Catches: as-of-L building its own atoms instead of sharing them.
        self._write_field_at(self.series, "seriesfield")
        self._write_field_at(self.root, "bookfield")
        self.service.read_metadata_schema()  # warm the whole chain's atoms
        with self._parse_spy() as spy:
            self.service.read_metadata_schema(up_to_layer_id=self._layer_id(self.series))
            self.assertEqual(spy.call_count, 0)

    # --- E. reload is stat-on-read; absence is data --------------------

    def test_a_schema_appearing_at_an_empty_layer_is_seen(self) -> None:
        # Catches: caching "absent" as permanent — addition blindness.
        self._write_field_at(self.root, "bookfield")
        self.assertNotIn("seriesfield", self.service.read_metadata_schema().fields)
        self._write_field_at(self.series, "seriesfield")  # a file appears where there was none
        self.assertIn("seriesfield", self.service.read_metadata_schema().fields)

    def test_a_deleted_schema_undefines_its_fields(self) -> None:
        # Catches: a parsed atom outliving its file.
        self._write_field_at(self.series, "seriesfield")
        self.assertIn("seriesfield", self.service.read_metadata_schema().fields)
        self._delete_schema_at(self.series)
        self.assertNotIn("seriesfield", self.service.read_metadata_schema().fields)

    def test_content_changed_under_an_older_mtime_is_still_reparsed(self) -> None:
        # Catches: a recency-based staleness check ("is the file newer?") instead
        # of equality — the backup-restore case the design names. A file restored
        # from backup lands an OLDER mtime yet is a real change.
        self._write_field_at(self.root, "before")
        self.assertIn("before", self.service.read_metadata_schema().fields)

        path = self.root / "metadata.schema.yaml"
        cached_mtime_ns = path.stat().st_mtime_ns
        self._write_field_at(self.root, "after")
        older = cached_mtime_ns - 10_000_000_000  # 10s before the cached stamp
        os.utime(path, ns=(older, older))

        fields = self.service.read_metadata_schema().fields
        self.assertIn("after", fields)
        self.assertNotIn("before", fields)

    # --- F. switch-stable ----------------------------------------------

    def test_switching_projects_and_back_does_not_evict(self) -> None:
        # Catches: dropping the schema cache on scope change — copying #392's
        # memo lifetime, which is wrong for a path-keyed cache.
        book02 = self.series / "book02"
        declare_full_chain(self.service, book02, self.base)
        self._write_field_at(self.root, "alpha")

        before_switch = self.service.read_metadata_schema(self.root)
        self.service.read_metadata_schema(book02)  # the "switch"
        after_switch = self.service.read_metadata_schema(self.root)
        self.assertIs(before_switch, after_switch)

    # --- G. one door ---------------------------------------------------

    def test_the_index_holds_the_doors_schema_not_a_private_merge(self) -> None:
        # Catches: a future second private producer — the "second merge with its
        # own bugs" the issue names. The index memo must hold the door's output.
        self._write_field_at(self.root, "alpha")
        resolved = self.service._resolve_index_cold(self.root)
        self.assertIs(resolved.schema, self.service.read_metadata_schema(self.root))


if __name__ == "__main__":
    unittest.main()
