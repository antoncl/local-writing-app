#!/usr/bin/env python3
"""Citation-rot checker (#397) — verify `path:line` claims made in prose.

A citation like ``_forward_refs_for_entry (`references.py:373-399`)`` is a
**claim about the code** embedded in prose that no gate ever reads. Code moves;
the claim does not. Rot is currently discovered by a fresh session reading an
issue, believing it, and sizing work against a repo state that no longer
exists. Same class of guard as the exemption ratchet and the file-size guard:
make drift un-ignorable rather than rely on someone remembering.

Three failure shapes; only two are trivial:

  * file gone or renamed              -> a path check finds it
  * line past the end of the file     -> a range check finds it
  * line valid, lands on unrelated code -> **only symbol anchoring finds it**

The third is the dangerous one — it looks fine, and it can land somewhere
plausibly adjacent, which is worse than landing nowhere. So each citation is
paired with the nearest identifier-looking word in the same line: this repo's
prose almost always names the symbol next to the citation, and that name is
what makes shape 3 detectable.

    1. file missing                       -> GONE
    2. line beyond EOF                    -> OUT OF RANGE
    3. named symbol spans/abuts the line  -> OK
    4. symbol defined elsewhere           -> MOVED (with the new location)
    5. symbol found nowhere               -> RENAMED OR DELETED

Bare symbol mentions with no line number get step 5 only — cheap, and it
catches the rename drift in ADR prose that let ADR-0040 v1 cite a function that
no longer exists.

**It flags. It never fixes.** Auto-rewriting a line number is tempting and
wrong: repointing a stale citation at whatever now occupies those lines yields
a citation that resolves cleanly and still does not support the sentence. That
converts visible rot into invisible rot.

Python symbol resolution (`def` / `class`) is the strong path. Other languages
get file+range checking only; a citation into a `.svelte` file is verified to
exist and to be in range, and no more.

Usage:
    python scripts/check_citations.py                       # everything
    python scripts/check_citations.py --changed-files f.txt # PR mode
    python scripts/check_citations.py --no-issues --memory-dir ~/…/memory
"""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Extensions a citation may point *into*. Deliberately wider than the source
# extensions we can symbol-anchor: a citation into project.yaml still benefits
# from the path and range checks.
CITED_EXTENSIONS = (
    "py",
    "svelte",
    "ts",
    "tsx",
    "js",
    "mjs",
    "css",
    "yaml",
    "yml",
    "json",
    "toml",
    "md",
)

# Files whose text is searched when asking "does this symbol exist anywhere?".
SEARCHABLE_SUFFIXES = {".py", ".svelte", ".ts", ".tsx", ".js", ".mjs"}

# How far above a `def` a citation may point and still count as pointing at it
# (decorators, a docstring-length comment block, an overload).
NEAR_LINES = 10

_EXT_ALTERNATION = "|".join(CITED_EXTENSIONS)

# `references.py:373-399`, `backend/app/main.py:12`, `App.svelte:4821–4830`.
CITATION_RE = re.compile(
    rf"(?P<path>[\w./\\-]+\.(?:{_EXT_ALTERNATION}))"
    r":(?P<start>\d+)(?:\s*[-–—]\s*(?P<end>\d+))?",
)

# Any file-path-looking token, cited or not. Used to mask paths out of a line
# before hunting for the symbol, so `project_service.py` in the prose is not
# mistaken for a snake_case identifier.
PATH_RE = re.compile(rf"[\w./\\-]+\.(?:{_EXT_ALTERNATION})(?::\d+(?:\s*[-–—]\s*\d+)?)?")

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Memory-file slugs (`decisions_metadata_revision`, `feedback_...`) are written
# in backticks and look exactly like snake_case symbols. They name a document,
# not code, and the documents live outside the repo — so they would be reported
# as deleted symbols, every week, forever.
MEMORY_SLUG_RE = re.compile(
    r"^(decisions|feedback|project|strategy|architecture|reference|user|ux|ui)_\w+_\w+$"
)
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
CAMEL_RE = re.compile(r"^[A-Za-z]+[A-Z]")

GONE = "GONE"
OUT_OF_RANGE = "OUT OF RANGE"
MOVED = "MOVED"
RENAMED_OR_DELETED = "RENAMED OR DELETED"
AMBIGUOUS = "AMBIGUOUS"
OK = "OK"

# Ordered worst-first, which is also the order they are reported in.
SEVERITY = [GONE, OUT_OF_RANGE, MOVED, RENAMED_OR_DELETED, AMBIGUOUS]


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Citation:
    """A `path:line` claim, plus the symbol the prose names next to it."""

    path: str
    start: int
    end: int
    symbol: str | None
    raw: str
    line_no: int  # line within the *source document*, for pointing a human at it


@dataclass(frozen=True)
class Mention:
    """A backticked identifier with no line number attached (step 5 only)."""

    symbol: str
    line_no: int


@dataclass
class Source:
    """A document that makes claims: an issue body, an ADR, a memory file."""

    label: str
    url: str
    text: str


@dataclass
class Finding:
    status: str
    source: Source
    detail: str
    citation: Citation | None = None
    mention: Mention | None = None
    # Repo-relative path the citation resolved to, when it resolved at all.
    resolved: str | None = None

    @property
    def line_no(self) -> int:
        return self.citation.line_no if self.citation else self.mention.line_no

    @property
    def subject(self) -> str:
        if self.citation:
            return self.citation.raw
        return f"`{self.mention.symbol}`"


def looks_like_symbol(word: str, line: str, end: int) -> bool:
    """Is `word` plausibly a code identifier rather than an English one?

    Three tells, any of which is enough: snake_case, CamelCase/camelCase, or a
    trailing `()`. English prose in this repo trips none of them.
    """
    if keyword.iskeyword(word) or len(word) < 3:
        return False
    if line[end : end + 2] == "()":
        return True
    if "_" in word and not word.startswith("__"):
        return True
    return bool(CAMEL_RE.match(word)) and not word.isupper()


def _mask_paths(line: str) -> str:
    """Blank out file paths so their segments cannot be read as identifiers."""
    return PATH_RE.sub(lambda m: " " * len(m.group(0)), line)


def _backtick_spans(line: str) -> list[tuple[int, int]]:
    return [m.span(1) for m in BACKTICK_RE.finditer(line)]


def nearest_symbol(window: str, cite_span: tuple[int, int]) -> str | None:
    """The identifier-looking word nearest the citation in its window.

    Candidates *before* the citation win: this repo's prose names the symbol
    and then parenthesises the location — ``_forward_refs_for_entry
    (`references.py:373-399`)`` — so a word that follows is usually part of the
    next clause, not the thing being cited. Then nearest wins, and backticks
    break ties.
    """
    masked = _mask_paths(window)
    ticks = _backtick_spans(window)
    best: tuple[int, int, int, str] | None = None
    for match in IDENT_RE.finditer(masked):
        start, end = match.span()
        if start >= cite_span[0] and end <= cite_span[1]:
            continue
        word = match.group(0)
        if not looks_like_symbol(word, window, end):
            continue
        ticked = any(a <= start and end <= b for a, b in ticks)
        before = end <= cite_span[0]
        distance = cite_span[0] - end if before else start - cite_span[1]
        rank = (0 if before else 1, distance, 0 if ticked else 1, word)
        if best is None or rank < best:
            best = rank
    return best[3] if best else None


def _windows(text: str):
    """Yield (line_no, window, offset) — the citation's line, plus the one
    above it when they belong to the same paragraph.

    Markdown prose wraps mid-sentence, so the symbol a citation belongs to
    lands on the previous line often enough to matter: ADR-0040's own
    `_forward_refs_for_entry` citation is split exactly that way.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        if previous.strip():
            yield index + 1, previous + "\n" + line, len(previous) + 1
        else:
            yield index + 1, line, 0


def extract_citations(text: str) -> list[Citation]:
    citations: list[Citation] = []
    for line_no, window, offset in _windows(text):
        line = window[offset:]
        for match in CITATION_RE.finditer(line):
            start = int(match.group("start"))
            end = int(match.group("end") or start)
            span = (match.start() + offset, match.end() + offset)
            citations.append(
                Citation(
                    path=match.group("path").replace("\\", "/"),
                    start=start,
                    end=max(start, end),
                    symbol=nearest_symbol(window, span),
                    raw=match.group(0),
                    line_no=line_no,
                )
            )
    return _dedupe(citations)


def _dedupe(citations: list[Citation]) -> list[Citation]:
    """Drop the bare half of a markdown link.

    `[models.py:762](backend/app/models.py:762)` is one claim written twice;
    reporting it twice doubles the noise for no information.
    """
    kept: list[Citation] = []
    for cite in citations:
        twin = any(
            other is not cite
            and other.line_no == cite.line_no
            and (other.start, other.end) == (cite.start, cite.end)
            and other.path.endswith("/" + cite.path)
            for other in citations
        )
        if not twin:
            kept.append(cite)
    return kept


def extract_mentions(text: str, cited: set[str]) -> list[Mention]:
    """Backticked identifiers carrying no line number.

    Restricted to backticks on purpose: an unticked word in prose is not a
    claim about the code, and treating it as one would drown the report.
    """
    seen: set[str] = set(cited)
    mentions: list[Mention] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in BACKTICK_RE.finditer(line):
            inner = match.group(1).strip()
            word = inner[:-2] if inner.endswith("()") else inner
            if not IDENT_RE.fullmatch(word) or word in seen:
                continue
            if MEMORY_SLUG_RE.match(word):
                continue
            if not looks_like_symbol(word, inner, len(word)):
                continue
            seen.add(word)
            mentions.append(Mention(symbol=word, line_no=line_no))
    return mentions


# --------------------------------------------------------------------------
# The repo, as the checker sees it
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Definition:
    path: str
    line: int
    end_line: int


class RepoIndex:
    """Tracked files, their lengths, and the Python `def`/`class` table.

    Constructed from an explicit file list so it can be pointed at a fixture
    tree in tests; `from_git` is the production entry point.
    """

    def __init__(self, root: Path, files: list[str]) -> None:
        self.root = Path(root)
        self.files = sorted(f.replace("\\", "/") for f in files)
        self._by_suffix: dict[str, list[str]] = {}
        for rel in self.files:
            self._by_suffix.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
        self._defs: dict[str, list[Definition]] | None = None
        self._text: dict[str, str] = {}

    @classmethod
    def from_git(cls, root: Path = REPO) -> RepoIndex:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return cls(root, [line for line in proc.stdout.splitlines() if line])

    def read(self, rel: str) -> str:
        if rel not in self._text:
            path = self.root / rel
            try:
                self._text[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._text[rel] = ""
        return self._text[rel]

    def line_count(self, rel: str) -> int:
        text = self.read(rel)
        return len(text.splitlines()) if text else 0

    def resolve(self, cited: str) -> list[str]:
        """Repo-relative paths a citation could mean.

        Citations are usually written bare (`references.py:373`), so a basename
        match is the common case; a partial path narrows it.
        """
        cited = cited.lstrip("./")
        exact = [rel for rel in self.files if rel == cited]
        if exact:
            return exact
        base = cited.rsplit("/", 1)[-1]
        candidates = self._by_suffix.get(base, [])
        if "/" in cited:
            tail = "/" + cited
            candidates = [rel for rel in candidates if rel.endswith(tail)]
        return candidates

    def definitions_in(self, rel: str) -> list[Definition]:
        return [d for defs in self.definitions().values() for d in defs if d.path == rel]

    def definitions(self) -> dict[str, list[Definition]]:
        if self._defs is None:
            self._defs = self._build_definitions()
        return self._defs

    def _build_definitions(self) -> dict[str, list[Definition]]:
        table: dict[str, list[Definition]] = {}
        for rel in self.files:
            if not rel.endswith(".py"):
                continue
            try:
                tree = ast.parse(self.read(rel))
            except (SyntaxError, ValueError):
                # A file we cannot parse simply contributes no anchors; that
                # degrades a citation to range-only, it does not fail the run.
                continue
            for node in ast.walk(tree):
                if not isinstance(
                    node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
                ):
                    continue
                end = getattr(node, "end_lineno", None) or node.lineno
                table.setdefault(node.name, []).append(
                    Definition(path=rel, line=node.lineno, end_line=end)
                )
        return table

    def mentions_anywhere(self, symbol: str) -> bool:
        """Does the token appear in any tracked source file?

        Deliberately textual and deliberately generous: the question at step 5
        is "did this name vanish", and a name that survives as a variable, a
        Svelte component or a dict key has not vanished.
        """
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        for rel in self.files:
            if Path(rel).suffix not in SEARCHABLE_SUFFIXES:
                continue
            if pattern.search(self.read(rel)):
                return True
        return False


# --------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------


def _anchors(cite: Citation, defs: list[Definition], rel: str, index: RepoIndex) -> bool:
    """Does one of these definitions actually cover the cited lines?

    Overlap is the strong answer. The slack below it is for a citation pointing
    at the decorator or comment block *above* a `def` — but only when the cited
    line is not already inside some *other* definition, which is precisely the
    shape-3 case and must not be forgiven.
    """
    mine = [d for d in defs if d.path == rel]
    if any(cite.start <= d.end_line and cite.end >= d.line for d in mine):
        return True
    if _inside_another_definition(cite, rel, index, {d.line for d in mine}):
        return False
    return any(0 <= d.line - cite.end <= NEAR_LINES for d in mine)


def _inside_another_definition(
    cite: Citation, rel: str, index: RepoIndex, own_lines: set[int]
) -> bool:
    for other in index.definitions_in(rel):
        if other.line in own_lines:
            continue
        if other.line <= cite.start <= other.end_line:
            return True
    return False


def _describe(defs: list[Definition]) -> str:
    return ", ".join(f"{d.path}:{d.line}" for d in defs[:4])


def check_citation(cite: Citation, index: RepoIndex, source: Source) -> Finding:
    """Verdict for one citation.

    Citations here are usually written bare (`schema.py:887`) and this repo has
    several `schema.py`. Every candidate is checked and a clean one settles it:
    if the citation makes sense against *some* file it could mean, that is not
    evidence of rot. AMBIGUOUS is reserved for the case where none of them work
    and we cannot say which one the author meant.
    """
    candidates = index.resolve(cite.path)
    if not candidates:
        return Finding(GONE, source, f"no tracked file named `{cite.path}`", cite)
    results = [_check_against(cite, rel, index, source) for rel in candidates]
    for result in results:
        if result.status == OK:
            return result
    if len(results) == 1:
        return results[0]
    detail = "; ".join(f"{r.resolved or cite.path}: {r.status.lower()}" for r in results[:4])
    return Finding(AMBIGUOUS, source, f"several files match — {detail}", cite)


def _check_against(cite: Citation, rel: str, index: RepoIndex, source: Source) -> Finding:
    total = index.line_count(rel)
    if cite.start > total or cite.end > total:
        return Finding(
            OUT_OF_RANGE, source, f"{rel} is {total} lines", cite, resolved=rel
        )

    if not cite.symbol or not rel.endswith(".py"):
        # Range-only verdict. Shipping this for .svelte/.ts beats delaying on a
        # TypeScript parser; the two cheap shapes are still caught.
        return Finding(OK, source, "in range", cite, resolved=rel)

    defs = index.definitions().get(cite.symbol, [])
    if not defs:
        if index.mentions_anywhere(cite.symbol):
            # Not a def/class — a variable, a constant, a string. Nothing to
            # anchor to, so we do not pretend to a verdict.
            return Finding(
                OK, source, f"in range (`{cite.symbol}` is not a def/class)", cite, resolved=rel
            )
        return Finding(
            RENAMED_OR_DELETED,
            source,
            f"`{cite.symbol}` appears nowhere in the repo — the sentence around "
            "the citation is probably wrong too, not just the number",
            cite,
            resolved=rel,
        )

    if _anchors(cite, defs, rel, index):
        return Finding(OK, source, f"`{cite.symbol}` is there", cite, resolved=rel)
    return Finding(
        MOVED,
        source,
        f"`{cite.symbol}` is now at {_describe(defs)}",
        cite,
        resolved=rel,
    )


def check_mention(mention: Mention, index: RepoIndex, source: Source) -> Finding:
    if index.mentions_anywhere(mention.symbol):
        return Finding(OK, source, "still present", mention=mention)
    return Finding(
        RENAMED_OR_DELETED,
        source,
        f"`{mention.symbol}` appears nowhere in the repo",
        mention=mention,
    )


def check_source(source: Source, index: RepoIndex, *, mentions: bool = True) -> list[Finding]:
    citations = extract_citations(source.text)
    findings = [check_citation(c, index, source) for c in citations]
    if mentions:
        cited = {c.symbol for c in citations if c.symbol}
        findings += [
            check_mention(m, index, source)
            for m in extract_mentions(source.text, cited)
        ]
    return findings


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------


def _gh(*args: str) -> str:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def open_issue_sources(limit: int = 500) -> list[Source]:
    raw = _gh(
        "issue",
        "list",
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        "number,title,body,url",
    )
    return [
        Source(label=f"#{i['number']} {i['title']}", url=i["url"], text=i["body"] or "")
        for i in json.loads(raw)
    ]


def doc_sources(index: RepoIndex) -> list[Source]:
    sources = []
    for rel in index.files:
        if rel.endswith(".md"):
            sources.append(Source(label=rel, url=rel, text=index.read(rel)))
    return sources


def memory_sources(directory: Path) -> list[Source]:
    """Memory files live outside the repo, so CI cannot see them.

    Passed explicitly with --memory-dir; the weekly run from a developer
    machine is where they get checked.
    """
    if not directory.is_dir():
        return []
    return [
        Source(label=f"memory/{p.name}", url=str(p), text=p.read_text(encoding="utf-8", errors="replace"))
        for p in sorted(directory.glob("*.md"))
    ]


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    sources_checked: int = 0
    citations_checked: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def rotted(self) -> list[Finding]:
        return [f for f in self.findings if f.status != OK]


def _relevant_path(finding: Finding) -> str | None:
    if finding.resolved:
        return finding.resolved
    return finding.citation.path if finding.citation else None


def filter_to_changed(findings: list[Finding], changed: list[str]) -> list[Finding]:
    """PR mode: only citations pointing into files this diff touched.

    A PR must not be told about rot it did not create — that is how an
    advisory check becomes noise people learn to skip.
    """
    wanted = {c.replace("\\", "/").lstrip("./") for c in changed}
    kept = []
    for finding in findings:
        path = _relevant_path(finding)
        if path is None:
            continue
        path = path.replace("\\", "/").lstrip("./")
        if any(w == path or w.endswith("/" + path) or path.endswith("/" + w) for w in wanted):
            kept.append(finding)
    return kept


def render_report(
    report: Report, *, title: str, sha: str | None = None, scope: str | None = None
) -> str:
    lines = [f"## {title}", ""]
    rotted = report.rotted
    provenance = f" against `{sha}`" if sha else ""
    lines.append(
        f"Checked {report.citations_checked} citations across "
        f"{report.sources_checked} documents{provenance}."
    )
    if scope:
        lines.append(f"Reporting only those pointing into {scope}.")
    for warning in report.warnings:
        lines.append(f"> ⚠ {warning}")
    lines.append("")
    if not rotted:
        lines.append("No rot found.")
        return "\n".join(lines) + "\n"

    lines.append(
        "This check **flags, it never fixes** — a repointed line number can "
        "resolve cleanly and still not support the sentence around it. Read "
        "the sentence, not just the number."
    )
    lines.append("")

    cited = [f for f in rotted if f.citation]
    bare = [f for f in rotted if f.mention]
    lines += _render_group(cited)
    if bare:
        lines.append("### Bare symbol mentions")
        lines.append("")
        lines.append(
            "Backticked names with no line number, found nowhere in the code. "
            "Lower confidence than the citations above: a name here may belong "
            "to user data, a schema field or another document's vocabulary "
            "rather than to a symbol that was renamed."
        )
        lines.append("")
        lines += _render_group(bare)
    return "\n".join(lines) + "\n"


def _render_group(findings: list[Finding]) -> list[str]:
    lines: list[str] = []
    by_source: dict[str, list[Finding]] = {}
    for finding in sorted(findings, key=lambda f: (SEVERITY.index(f.status), f.line_no)):
        by_source.setdefault(finding.source.label, []).append(finding)
    for label, group in by_source.items():
        lines.append(f"#### {label}" if group[0].mention else f"### {label}")
        for finding in group:
            lines.append(
                f"- **{finding.status}** {finding.subject} "
                f"(line {finding.line_no}) — {finding.detail}"
            )
        lines.append("")
    return lines


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def collect_sources(
    args: argparse.Namespace, index: RepoIndex
) -> tuple[list[Source], list[str]]:
    sources: list[Source] = []
    warnings: list[str] = []
    if not args.no_docs:
        sources += doc_sources(index)
    if args.memory_dir:
        sources += memory_sources(Path(args.memory_dir).expanduser())
    if not args.no_issues:
        try:
            sources += open_issue_sources()
        except (RuntimeError, OSError, json.JSONDecodeError) as exc:
            # A `gh` hiccup must not turn an advisory check into a red build.
            # Say so in the report instead — a silently issue-less run would
            # read as "no rot in any issue", which is worse than a warning.
            warnings.append(f"could not read open issues: {exc}")
    return sources, warnings


def run(args: argparse.Namespace) -> Report:
    index = RepoIndex.from_git(Path(args.repo))
    sources, warnings = collect_sources(args, index)
    report = Report(sources_checked=len(sources), warnings=warnings)
    for source in sources:
        findings = check_source(source, index, mentions=not args.no_mentions)
        report.citations_checked += sum(1 for f in findings if f.citation)
        report.findings += findings
    if args.changed_files:
        changed = [
            line.strip()
            for line in Path(args.changed_files).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        report.findings = filter_to_changed(report.findings, changed)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--no-issues", action="store_true", help="skip open GitHub issues")
    parser.add_argument("--no-docs", action="store_true", help="skip tracked markdown")
    parser.add_argument("--no-mentions", action="store_true", help="citations only")
    parser.add_argument("--memory-dir", help="directory of memory *.md files (outside the repo)")
    parser.add_argument("--changed-files", help="file listing changed paths; restricts the report to them")
    parser.add_argument("--title", default="Citation rot")
    parser.add_argument("--sha", help="commit the report was produced against")
    parser.add_argument("--out", help="write the markdown report here instead of stdout")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    report = run(args)
    scope = "the files this diff touches" if args.changed_files else None
    markdown = render_report(report, title=args.title, sha=args.sha, scope=scope)
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    # Always 0. This is advisory by design: a PR must not go red because an
    # unrelated issue got stale. The workflow decides what to do with the text.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
