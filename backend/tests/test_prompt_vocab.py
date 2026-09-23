"""ADR-0092 §7.2: the Deprecated table — the reference parser and the drift
gate both need to know a symbol can be documented as deprecated (still
registered, no longer offered by completion) rather than only helper/retired.

Covers the fifth table `scripts/prompt_vocab.py` parses and the extra rules
`scripts/check_prompt_vocab_docs.py` applies around it:

- a `## Deprecated` table parses to kind ``"deprecated"``;
- a registered global documented ONLY in the Deprecated table is not flagged
  "undocumented" (the drift gate accepts it);
- a Deprecated row naming something that is NOT registered is a problem
  ("remove the row" — the alias was actually deleted); and
- a name listed in BOTH the Helpers and Deprecated tables is a problem (it
  cannot be both current and deprecated).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import gen_prompt_vocab  # noqa: E402
from check_prompt_vocab_docs import Vocab, _diff_problems  # noqa: E402
from prompt_vocab import load_reference, parse_reference  # noqa: E402

_REFERENCE_FIXTURE = """\
## Variables

| Name | Type / shape |
| --- | --- |
| `scene` | The scene. |
| `inputs` | The inputs. |

## Helpers

| Call | Returns |
| --- | --- |
| `entry(x)` | A node. |
| `fields(x)` | Fields. |
| `use(node)` | Places a node. |
| `field_contract` | The contract. |
| `auto_lore()` | Enables lore. |

## Filters

| Filter | Returns |
| --- | --- |
| `value \\| json` | JSON. |

## Tags

| Tag | Effect |
| --- | --- |
| `{% role "system" %}` | Roles. |
| `{% do %}` | Side effect. |

## Deprecated

Still works, still documented, removed at 1.0.

| Call | Use instead |
| --- | --- |
| `use_lore()` | `auto_lore()`. |

## Retired

`base(x)` → `original(x)`
"""


class ParseDeprecatedTableTests(unittest.TestCase):
    def test_deprecated_row_parses_to_kind_deprecated(self) -> None:
        symbols = parse_reference(_REFERENCE_FIXTURE)
        by_name = {s.name: s for s in symbols}
        self.assertEqual(by_name["use_lore"].kind, "deprecated")
        self.assertEqual(by_name["use_lore"].signature, "use_lore()")
        self.assertIn("auto_lore", by_name)
        self.assertEqual(by_name["auto_lore"].kind, "helper")


def _vocab(**overrides) -> Vocab:
    base = {
        "env_globals": {"entry", "fields", "use", "field_contract", "auto_lore"},
        "env_filters": {"json"},
        "env_vars": {"scene", "inputs"},
        "tags": set(),  # tags aren't under test here; avoid the md-mention check
        "doc_helpers": {"entry", "fields", "use", "field_contract", "auto_lore"},
        "doc_filters": {"json"},
        "doc_vars": {"scene", "inputs"},
        "doc_deprecated": set(),
    }
    base.update(overrides)
    return Vocab(**base)


class DeprecatedGateTests(unittest.TestCase):
    """`_diff_problems` treats the Deprecated table as a second "documented"
    source for a registered global, with its own failure modes."""

    def test_a_registered_deprecated_alias_is_accepted(self) -> None:
        # use_lore is registered (still an alias) and documented ONLY as
        # deprecated — not a "helper undocumented" problem.
        v = _vocab(
            env_globals={"entry", "fields", "use", "field_contract", "auto_lore", "use_lore"},
            doc_deprecated={"use_lore"},
        )
        problems = _diff_problems(v, "")
        self.assertEqual(problems, [])

    def test_deprecated_row_without_registration_is_a_problem(self) -> None:
        # The row still names an alias, but the alias was actually removed —
        # the doc must drop the row.
        v = _vocab(doc_deprecated={"use_lore"})
        problems = _diff_problems(v, "")
        self.assertTrue(
            any("deprecated helper `use_lore`" in p and "remove the row" in p for p in problems),
            problems,
        )

    def test_name_in_both_helpers_and_deprecated_is_a_problem(self) -> None:
        v = _vocab(
            env_globals={"entry", "fields", "use", "field_contract", "auto_lore"},
            doc_helpers={"entry", "fields", "use", "field_contract", "auto_lore"},
            doc_deprecated={"auto_lore"},
        )
        problems = _diff_problems(v, "")
        self.assertTrue(
            any("`auto_lore` is listed as both a helper and deprecated" in p for p in problems),
            problems,
        )


class RealReferenceTests(unittest.TestCase):
    """ADR-0093 §1: the real `docs/prompts/reference.md` and its generated
    manifest, not the fixture above."""

    def test_use_row_parses_with_the_snapshot_keyword(self) -> None:
        symbols = parse_reference(load_reference())
        by_name = {s.name: s for s in symbols}
        self.assertIn("use", by_name)
        self.assertEqual(by_name["use"].kind, "helper")
        self.assertIn("snapshot=id", by_name["use"].signature)

    def test_committed_manifest_equals_the_generators_output(self) -> None:
        current = gen_prompt_vocab.OUT.read_text(encoding="utf-8")
        self.assertEqual(current, gen_prompt_vocab.render())


if __name__ == "__main__":
    unittest.main()
