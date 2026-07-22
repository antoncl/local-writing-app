"""The citation-rot checker (#397).

The headline case is shape 3: a citation whose line number is still *valid* but
now lands on unrelated code. Shapes 1 and 2 (missing file, line past EOF) are
trivially detectable and are covered here mostly so a refactor cannot lose
them; shape 3 is the one that motivated the tool, because it looks fine.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_script(name: str):
    """Import a module from `scripts/`, which is not a package."""
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_gate_{name}", path)
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: `@dataclass` resolves annotations through
    # sys.modules, and blows up on a module that is not there yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cc = _load_script("check_citations")


# --------------------------------------------------------------------------
# A fixture repo whose code has already moved out from under the prose.
# --------------------------------------------------------------------------

FILES = {
    "backend/app/references.py": textwrap.dedent(
        '''\
        """Reference extraction."""

        CACHE_VERSION = 3


        def unrelated_helper(a, b):
            """Occupies the lines a stale citation now points at."""
            return a + b


        def forward_refs(entry):
            """Moved down the file since the citation was written."""
            return entry.refs
        '''
    ),
    "backend/app/schema.py": "def layer_folders():\n    return []\n",
    "backend/app/models/schema.py": "FIELD = 1\n",
    "frontend/src/NodeRow.svelte": "<div>row</div>\n" * 40,
}


@pytest.fixture
def index(tmp_path: Path):
    for rel, text in FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return cc.RepoIndex(tmp_path, list(FILES))


def check(index, text: str):
    source = cc.Source(label="#1 fixture", url="", text=text)
    return cc.check_source(source, index, mentions=False)


def one(index, text: str):
    findings = check(index, text)
    assert len(findings) == 1, [f.subject for f in findings]
    return findings[0]


# --------------------------------------------------------------------------
# The five outcomes
# --------------------------------------------------------------------------


def test_shape_3_valid_line_landing_on_unrelated_code(index):
    """THE headline case: line 6 exists, and is not `forward_refs` any more.

    A range check passes here. Only anchoring to the symbol the prose names
    catches it — and the report has to say where the symbol actually went, or
    the reader has to go find it themselves.
    """
    finding = one(index, "`forward_refs` (`references.py:6`) resolves the edges.")
    assert finding.status == cc.MOVED
    assert "references.py:11" in finding.detail


def test_missing_file_is_gone(index):
    finding = one(index, "See `services/project_service.py:1800` for the walk.")
    assert finding.status == cc.GONE


def test_line_past_end_of_file_is_out_of_range(index):
    finding = one(index, "`forward_refs` (`references.py:1800`) does the work.")
    assert finding.status == cc.OUT_OF_RANGE
    assert "13 lines" in finding.detail


def test_symbol_found_nowhere_needs_a_human(index):
    finding = one(index, "`_forward_refs_for_entry` (`references.py:11`) resolves.")
    assert finding.status == cc.RENAMED_OR_DELETED


def test_citation_that_still_holds_is_ok(index):
    finding = one(index, "`forward_refs` (`references.py:11-13`) resolves the edges.")
    assert finding.status == cc.OK


def test_citation_just_above_the_def_still_anchors(index):
    """Prose points at a decorator or the comment above as often as the `def`."""
    assert one(index, "`forward_refs` (`references.py:10`) resolves.").status == cc.OK


def test_citation_inside_the_body_anchors_to_the_enclosing_def(index):
    assert one(index, "`forward_refs` (`references.py:13`) returns refs.").status == cc.OK


# --------------------------------------------------------------------------
# Symbol extraction — the part that makes shape 3 detectable at all
# --------------------------------------------------------------------------


def test_symbol_is_taken_from_before_the_citation(index):
    """`entry_type` follows the citation; the cited symbol precedes it.

    Verbatim shape from ADR-0040, which is what taught us to prefer the
    preceding word.
    """
    citations = cc.extract_citations(
        "- Edge extraction is schema-driven — `forward_refs`\n"
        "  (`references.py:11`) resolves `entry_type -> field`."
    )
    assert [c.symbol for c in citations] == ["forward_refs"]


def test_symbol_may_sit_on_the_previous_line(index):
    """Markdown wraps mid-sentence; the symbol lands above the citation."""
    finding = one(
        index,
        "- Edge extraction is schema-driven — `_forward_refs_for_entry`\n"
        "  (`references.py:11`) resolves `entry_type -> field`.",
    )
    assert finding.status == cc.RENAMED_OR_DELETED
    assert "_forward_refs_for_entry" in finding.detail


def test_a_filename_in_the_prose_is_not_mistaken_for_a_symbol(index):
    """`project_service.py` is snake_case too. Masking paths is what saves it."""
    citations = cc.extract_citations("Split out of project_service.py — `references.py:11`.")
    assert citations[0].symbol is None


def test_a_markdown_link_is_one_citation_not_two(index):
    """`[models.py:7](backend/app/models.py:7)` is one claim written twice."""
    citations = cc.extract_citations("Same shape as [references.py:6](backend/app/references.py:6).")
    assert [c.path for c in citations] == ["backend/app/references.py"]


def test_a_paragraph_break_does_not_leak_a_symbol_across(index):
    citations = cc.extract_citations("`forward_refs` was renamed.\n\n`references.py:6` is the spot.")
    assert citations[0].symbol is None


# --------------------------------------------------------------------------
# Non-Python, ambiguity, bare mentions
# --------------------------------------------------------------------------


def test_svelte_gets_file_and_range_only(index):
    """No TypeScript parser — shipping range checking beats delaying on one."""
    assert one(index, "`NodeRow` (`NodeRow.svelte:12`) renders it.").status == cc.OK
    assert one(index, "`NodeRow` (`NodeRow.svelte:900`) renders it.").status == cc.OUT_OF_RANGE


def test_a_clean_candidate_settles_an_ambiguous_basename(index):
    """Two `schema.py` exist; the citation makes sense against one of them."""
    finding = one(index, "`layer_folders` (`schema.py:1`) walks the chain.")
    assert finding.status == cc.OK
    assert finding.resolved == "backend/app/schema.py"


def test_ambiguous_only_when_no_candidate_works(index):
    finding = one(index, "`layer_folders` (`schema.py:900`) walks the chain.")
    assert finding.status == cc.AMBIGUOUS
    assert "backend/app/models/schema.py" in finding.detail


def test_bare_mention_of_a_vanished_symbol_is_flagged(index):
    source = cc.Source(label="ADR", url="", text="The `_forward_refs_for_entry` rule still holds.")
    findings = [f for f in cc.check_source(source, index) if f.mention]
    assert [(f.status, f.mention.symbol) for f in findings] == [
        (cc.RENAMED_OR_DELETED, "_forward_refs_for_entry")
    ]


def test_a_name_that_survives_only_in_prose_has_still_vanished(tmp_path):
    """The checker blinded itself this way within a day of merging.

    Naming a genuinely deleted function in its own docstring and test fixtures
    made `mentions_anywhere` find it, which downgraded the flagship finding to
    OK — the gate eroded by describing what it looks for. Python comments and
    string literals are code's prose, and prose about a name is not the name.
    """
    (tmp_path / "doc.py").write_text(
        '"""Once resolved by long_gone_helper, which no longer exists."""\n'
        "# long_gone_helper used to live here\n"
        "SURVIVOR = 1\n",
        encoding="utf-8",
    )
    index = cc.RepoIndex(tmp_path, ["doc.py"])
    assert not index.mentions_anywhere("long_gone_helper")
    assert index.mentions_anywhere("SURVIVOR")


def test_bare_mention_of_a_surviving_name_is_quiet(index):
    source = cc.Source(label="ADR", url="", text="The `unrelated_helper` and `CACHE_VERSION` still exist.")
    assert all(f.status == cc.OK for f in cc.check_source(source, index))


def test_a_source_carrying_the_ignore_marker_is_skipped(index):
    """The weekly report is an open issue, so the checker reads its own output.

    Without the marker it re-flags every citation last week's report quoted —
    68 of 245 findings on the run that found this (#411). A marker rather than
    a hardcoded issue number: a memo quoting historical citations on purpose
    needs the same way out.
    """
    text = f"{cc.IGNORE_MARKER}\n- **MOVED** `references.py:6` — `forward_refs` moved."
    assert cc.check_source(cc.Source(label="#407 report", url="", text=text), index) == []


def test_memory_slugs_are_not_treated_as_symbols(index):
    """They name documents that live outside the repo, and always would fail."""
    source = cc.Source(label="ADR", url="", text="See `decisions_node_edit_gesture`.")
    assert [f for f in cc.check_source(source, index) if f.mention] == []


# --------------------------------------------------------------------------
# PR mode
# --------------------------------------------------------------------------


def test_pr_mode_reports_only_citations_into_touched_files(index):
    findings = check(
        index,
        "`forward_refs` (`references.py:6`) resolves.\n"
        "`layer_folders` (`schema.py:900`) walks.\n",
    )
    kept = cc.filter_to_changed(findings, ["backend/app/references.py"])
    assert [f.status for f in kept] == [cc.MOVED]


def test_pr_mode_keeps_a_missing_file_by_its_cited_path(index):
    findings = check(index, "See `services/project_service.py:1800`.")
    kept = cc.filter_to_changed(findings, ["backend/app/services/project_service.py"])
    assert [f.status for f in kept] == [cc.GONE]


def test_pr_mode_drops_bare_mentions(index):
    """A mention has no file, so it can never be attributed to this diff."""
    source = cc.Source(label="ADR", url="", text="The `_forward_refs_for_entry` rule.")
    findings = cc.check_source(source, index)
    assert cc.filter_to_changed(findings, ["backend/app/references.py"]) == []


# --------------------------------------------------------------------------
# Pinned citations (#412) — "Verified against `<ref>`"
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return proc.stdout


@pytest.fixture
def pinned_repo(tmp_path: Path):
    """A repo where the cited function has since moved down its file.

    Tagged at the moment the citation was written, so `v1` is what a document
    pinned to it should be judged against.
    """
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    target = tmp_path / "mod.py"
    target.write_text("def forward_refs(entry):\n    return entry.refs\n", encoding="utf-8")
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-qm", "first")
    _git(tmp_path, "tag", "v1")
    target.write_text(
        "def added_later(a):\n    return a\n\n\ndef forward_refs(entry):\n    return entry.refs\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "mod.py")
    _git(tmp_path, "commit", "-qm", "second")
    return tmp_path


def test_provenance_header_is_recognised():
    assert cc.provenance_ref("> **Verified against `v0.6.5` (2026-07-22).**") == "v0.6.5"
    assert cc.provenance_ref("Written against `052895c`, out of the audit.") == "052895c"
    assert cc.provenance_ref("No provenance here.") is None


def test_a_pinned_citation_that_held_at_its_ref_is_silent(pinned_repo):
    """The whole point: a pinned citation cannot rot.

    Line 1 was `forward_refs` at `v1` and is `added_later` at HEAD. Judged
    against HEAD this is the headline shape-3 finding; judged against the ref
    the document names, it is simply correct.
    """
    text = "Verified against `v1`. `forward_refs` (`mod.py:1`) resolves the edges."
    source = cc.Source(label="ADR", url="", text=text)

    at_head = cc.check_source(source, cc.RepoIndex(pinned_repo, ["mod.py"]), mentions=False)
    assert [f.status for f in at_head] == [cc.MOVED]

    at_ref = cc.check_source(source, cc.RefIndex.at(pinned_repo, "v1"), mentions=False)
    assert [f.status for f in at_ref] == [cc.OK]


def test_a_pinned_citation_that_was_wrong_at_its_own_ref_is_still_reported(pinned_repo):
    """The write-time check the pin makes possible — a typo'd line number."""
    text = "Verified against `v1`. `forward_refs` (`mod.py:900`) resolves."
    findings = cc.check_source(
        cc.Source(label="ADR", url="", text=text),
        cc.RefIndex.at(pinned_repo, "v1"),
        mentions=False,
    )
    assert [f.status for f in findings] == [cc.OUT_OF_RANGE]


def test_a_pinned_document_still_reports_a_symbol_that_never_existed(pinned_repo):
    text = "Verified against `v1`. `never_existed` (`mod.py:1`) resolves."
    findings = cc.check_source(
        cc.Source(label="ADR", url="", text=text),
        cc.RefIndex.at(pinned_repo, "v1"),
        mentions=False,
    )
    assert [f.status for f in findings] == [cc.RENAMED_OR_DELETED]


def test_an_unresolvable_ref_never_silently_passes(pinned_repo):
    """A shallow clone, or a sha squashed away at merge.

    `None` is what makes `run` emit UNVERIFIABLE rather than quietly checking
    against HEAD, which would report drift the pin exists to prevent.
    """
    assert cc.RefIndex.at(pinned_repo, "v99-never-tagged") is None


def test_the_pinned_roster_is_reported_once_not_per_citation():
    report = cc.Report(pinned=[("ADR-0045", "6284bda"), ("#310", "052895c")])
    markdown = cc.render_report(report, title="Citation rot")
    assert "2 document(s) pin their citations to an earlier ref" in markdown
    assert "052895c, 6284bda" in markdown


# --------------------------------------------------------------------------
# It flags, it never fixes
# --------------------------------------------------------------------------


def test_the_checker_never_writes_to_an_issue_or_a_source_file():
    """Auto-repointing a citation converts visible rot into invisible rot.

    Pinned as a property of the source, not of a run: the only `gh` verb this
    module may reach for is a read.
    """
    text = (REPO / "scripts" / "check_citations.py").read_text(encoding="utf-8")
    for forbidden in ('"edit"', '"comment"', '"create"', "write_text(", "issue edit"):
        occurrences = text.count(forbidden)
        if forbidden == "write_text(":
            # Exactly one: --out, which writes the report to a path the caller
            # names. Nothing else in the module may write.
            assert occurrences == 1, "check_citations.py grew a second writer"
        else:
            assert occurrences == 0, f"check_citations.py reaches for gh {forbidden}"


def test_report_renders_the_never_fixes_warning(index):
    report = cc.Report(findings=check(index, "`forward_refs` (`references.py:6`) resolves."))
    report.citations_checked = 1
    report.sources_checked = 1
    markdown = cc.render_report(report, title="Citation rot", sha="abc1234")
    assert "flags, it never fixes" in markdown
    assert "abc1234" in markdown
    assert "MOVED" in markdown


def test_an_unreachable_gh_is_a_warning_in_the_report_not_a_red_build(index, monkeypatch):
    """A run that silently checked no issues reads as "no rot in any issue"."""
    monkeypatch.setattr(cc, "RepoIndex", type("_", (), {"from_git": staticmethod(lambda _: index)}))
    monkeypatch.setattr(cc, "open_issue_sources", _boom)
    args = cc.build_parser().parse_args(["--no-docs"])
    report = cc.run(args)
    assert report.warnings and "gh exploded" in report.warnings[0]
    assert "⚠" in cc.render_report(report, title="Citation rot")


def _boom():
    raise RuntimeError("gh exploded")


def test_clean_report_says_so(index):
    markdown = cc.render_report(cc.Report(), title="Citation rot")
    assert "No rot found." in markdown


def test_documentation_about_the_convention_does_not_pin_itself():
    """The ADR README shows the header; it must not thereby adopt it.

    A ref is a sha or a version tag, never a placeholder or a branch name —
    branches move, which defeats the point of pinning.
    """
    assert cc.provenance_ref("> **Verified against `<tag>` (YYYY-MM-DD).**") is None
    assert cc.provenance_ref("Verified against `main`.") is None
