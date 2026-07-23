"""Node-index / cache benchmark for ADR-0040 (project hierarchies, #7).

Measures the real cost of building, persisting and maintaining the backend node
index across a deep ancestor chain.

**This bench drives the real `ProjectService`.** It does not reimplement the
parse path, the schema merge or the edge extraction — earlier revisions did, and
drifted: the fixtures carried no `metadata.schema.yaml` and used undeclared
`ref_*` field names, so the replica extracted edges the real (schema-driven)
code would never have produced. Every number below therefore comes from the
same call the app makes.

Questions answered:
  Q1  footprint  — what does holding the index / metadata / bodies cost?
  Q2  cold build — `_build_node_index()` over one book's ancestor chain (since
                   #305 that one pass also yields the edges + reverse map, so
                   the graph is a projection, not a second walk)
  Q3  schema     — `read_metadata_schema()`, the uncached per-layer merge that
                   ADR-0039 deepens
  Q4  snapshot   — dump / load / rehydrate to real NodeIndexEntry objects
  Q5  staleness  — the manifest stat sweep that detects external edits
  Q6  increment  — re-parse N changed files
  Q7  query      — dict vs edge-list scan vs reverse adjacency vs SQLite

Fixtures are generated under `tmp/` (gitignored); only this script is tracked.

Run:
    backend/.venv/Scripts/python.exe scripts/benchmark/cache/hierarchy_bench.py
    ... --regen            regenerate fixtures
    ... weber              run one scale only
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services import machine_settings as ms_service  # noqa: E402
from app.services.project_service import ProjectService  # noqa: E402

FIXTURE_ROOT = REPO_ROOT / "tmp" / "benchmark-fixtures" / "cache"
LOREM = ["the", "ship", "translated", "into", "hyper", "space", "above", "the", "planet", "while", "the", "admiral", "considered", "her", "orders", "and", "the", "fleet", "held", "station", "against", "the", "coming", "storm", "of", "missiles", "treaties", "and", "the", "long", "politics", "of", "the", "star", "kingdom", "and", "its", "allies"]

# Fields the DEFAULT schema really declares as entity_ref / entity_ref_list.
# Using anything else yields zero edges under the real extractor.
LORE_REF_FIELD = "related_entries"  # entity_ref_list on lore:base
SCENE_REF_FIELD = "characters"  # entity_ref_list on scene:scene
SCENE_POV_FIELD = "pov"  # entity_ref on scene:scene


@dataclass
class Scale:
    name: str
    universes: int
    books_per_universe: int
    base_lore: int
    universe_lore: int
    series_lore: int
    book_lore: int
    scenes_per_book: int
    body_words: int
    refs_per_entry: int


SCALES = [
    Scale("small", 1, 5, 50, 400, 80, 30, 40, 350, 5),
    Scale("weber", 4, 15, 100, 1200, 200, 40, 60, 400, 6),
    Scale("huge", 6, 20, 200, 2500, 300, 50, 70, 450, 7),
]


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------
def deep_size(obj, _seen: set[int] | None = None) -> int:
    """Object-graph footprint. An optimistic floor: shared/interned strings are
    counted once, and fixture values repeat more than real prose would."""
    if _seen is None:
        _seen = set()
    oid = id(obj)
    if oid in _seen:
        return 0
    _seen.add(oid)
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for key, value in obj.items():
            size += deep_size(key, _seen) + deep_size(value, _seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            size += deep_size(item, _seen)
    elif is_dataclass(obj) and not isinstance(obj, type):
        # `fields()`, not `vars()` — a slots dataclass (ReferenceEdge) has no
        # __dict__ and vars() raises on it. Count the instance __dict__ where
        # there is one: it is ~88 B of pure per-object overhead, and leaving it
        # out made `slots=True` look free of charge in both directions.
        instance_dict = getattr(obj, "__dict__", None)
        if instance_dict is not None:
            size += sys.getsizeof(instance_dict)
        for f in dataclass_fields(obj):
            size += deep_size(getattr(obj, f.name), _seen)
    elif isinstance(obj, Path):
        size += deep_size(str(obj), _seen)
    return size


def mb(value: int) -> str:
    return f"{value / 1_048_576:.1f} MB"


def time_it(fn, *args):
    gc.collect()
    start = time.perf_counter()
    result = fn(*args)
    return time.perf_counter() - start, result


# ---------------------------------------------------------------------------
# Fixture generation
# ---------------------------------------------------------------------------
def _body(words: int) -> str:
    out: list[str] = []
    for i in range(words):
        out.append(LOREM[i % len(LOREM)])
        if i and i % 18 == 0:
            out.append("\n\n")
    return "# Overview\n\n" + " ".join(out) + "\n"


def _front_matter(node_id: str, title: str, entry_type: str, metadata: dict) -> str:
    lines = [f"id: {node_id}", f"title: {title}", f"entry_type: {entry_type}", "metadata:"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"  {key}:")
            lines.extend(f"    - {item}" for item in value)
        else:
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def _lore_metadata(idx: int, ref_pool: list[str], refs_per: int) -> dict:
    """~15 scalar fields plus the schema-declared entity_ref_list."""
    metadata: dict = {
        "rank": ["Ensign", "Commander", "Captain", "Commodore", "Admiral"][idx % 5],
        "species": ["human", "treecat", "grayson"][idx % 3],
        "status": "alive" if idx % 4 else "deceased",
        "birth_year": 1800 + (idx % 200),
        "importance": idx % 10,
        "faction": f"faction_{idx % 12}",
        "region": f"sector_{idx % 30}",
        "epithet": f"epithet-{idx % 50}",
        "aliases": [f"alias{idx}a", f"alias{idx}b"],
        "tags": [f"tag{idx % 20}", f"tag{(idx + 3) % 20}"],
    }
    if ref_pool:
        metadata[LORE_REF_FIELD] = [ref_pool[(idx * 7 + j) % len(ref_pool)] for j in range(refs_per)]
    return metadata


def _write_layer_schema(folder: Path, layer: str) -> None:
    """A per-layer metadata.schema.yaml, so the layered merge is really exercised.

    Each layer adds a field and a local entry type; nearer layers override
    farther ones, which is the merge ADR-0039 deepens."""
    text = (
        "version: 1\n"
        "fields:\n"
        f"  {layer}_note:\n"
        f"    name: {layer.title()} Note\n"
        "    type: text\n"
        f"  {layer}_link:\n"
        f"    name: {layer.title()} Link\n"
        "    type: entity_ref\n"
        "entry_types:\n"
        f"  lore:{layer}_entity:\n"
        f"    name: {layer.title()} Entity\n"
        "    kind: lore\n"
        "    parent: lore:base\n"
        "    fields:\n"
        f"      - {layer}_note\n"
        f"      - {layer}_link\n"
    )
    (folder / "metadata.schema.yaml").write_text(text, encoding="utf-8")


def _write_project_yaml(folder: Path, base: Path) -> None:
    """A layer of the fixture chain: a manifest plus its declaration.

    Two things this has to say, and it used to say neither correctly:

    * `inherits` — since #309 inheritance is **declared**. A manifest alone
      makes a folder a project; it does not make it a layer of anything.
    * nothing about the bound — since #429 the walk stops at the *machine*
      root, so `settings.projects_base_folder` is ignored. Writing it made the
      generated tree look layered while every project actually walked alone,
      and the bench happily reported 4-layer numbers for a 1-layer chain.

    `set_machine_root` below is what makes `base` reachable at all.
    """
    folder.mkdir(parents=True, exist_ok=True)
    ancestors = []
    current = folder.parent
    while True:
        ancestors.append(os.path.relpath(current, folder).replace("\\", "/"))
        if current == base:
            break
        current = current.parent
    inherits = "".join(f"  - {entry}\n" for entry in reversed(ancestors)) if folder != base else ""
    text = f"title: {folder.name}\n"
    if inherits:
        text += f"inherits:\n{inherits}"
    (folder / "project.yaml").write_text(text, encoding="utf-8")


def set_machine_root(base: Path) -> None:
    """Point the walk's bound (#429) at this fixture tree.

    Also isolates the bench from the developer's real machine config: without
    this it would read `%APPDATA%`, so the chain depth would depend on whoever
    happened to run it, and a stray `default_projects_folder` could make the
    numbers unreproducible.
    """
    config_dir = FIXTURE_ROOT / ".machine"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(f"default_projects_folder: {base}\n", encoding="utf-8")
    ms_service.config_path = lambda: config_path  # type: ignore[assignment]


def _write_lore(folder: Path, prefix: str, count: int, start: int, pool: list[str], sc: Scale) -> list[str]:
    lore_dir = folder / "lore"
    lore_dir.mkdir(parents=True, exist_ok=True)
    body = _body(sc.body_words)
    ids: list[str] = []
    for i in range(count):
        gi = start + i
        node_id = f"lore_{prefix}_{gi:06d}"
        ids.append(node_id)
        metadata = _lore_metadata(gi, pool, sc.refs_per_entry)
        fm = _front_matter(node_id, f"{prefix.title()} Entry {gi}", "lore:character", metadata)
        (lore_dir / f"{node_id}.md").write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")
    return ids


def _write_scenes(folder: Path, prefix: str, count: int, start: int, pool: list[str], sc: Scale) -> None:
    scenes_dir = folder / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    body = _body(sc.body_words * 4)
    for i in range(count):
        gi = start + i
        metadata = {"status": "draft"}
        if pool:
            metadata[SCENE_POV_FIELD] = pool[gi % len(pool)]
            metadata[SCENE_REF_FIELD] = [pool[(gi * 3 + j) % len(pool)] for j in range(3)]
        fm = _front_matter(f"scene_{prefix}_{gi:06d}", f"Scene {gi}", "scene:scene", metadata)
        (scenes_dir / f"scene_{prefix}_{gi:06d}.md").write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")


def _generate_universe(base: Path, uni_index: int, base_ids: list[str], sc: Scale, counter: int) -> int:
    uni = base / f"universe_{uni_index:02d}"
    _write_project_yaml(uni, base)
    _write_layer_schema(uni, "universe")
    uni_ids = _write_lore(uni, f"u{uni_index}", sc.universe_lore, counter, base_ids, sc)
    counter += sc.universe_lore

    series = uni / "series_00"
    _write_project_yaml(series, base)
    _write_layer_schema(series, "series")
    series_ids = _write_lore(series, f"s{uni_index}", sc.series_lore, counter, base_ids + uni_ids, sc)
    counter += sc.series_lore

    pool = base_ids + uni_ids + series_ids
    for book_index in range(sc.books_per_universe):
        book = series / f"book_{book_index:02d}"
        _write_project_yaml(book, base)
        _write_layer_schema(book, "book")
        _write_lore(book, f"b{uni_index}_{book_index}", sc.book_lore, counter, pool, sc)
        counter += sc.book_lore
        _write_scenes(book, f"b{uni_index}_{book_index}", sc.scenes_per_book, counter, pool, sc)
        counter += sc.scenes_per_book
    return counter


def generate(sc: Scale) -> Path:
    root = FIXTURE_ROOT / f"fixture_{sc.name}"
    if root.exists():
        shutil.rmtree(root)
    _write_project_yaml(root, root)
    _write_layer_schema(root, "base")
    counter = 0
    base_ids = _write_lore(root, "base", sc.base_lore, counter, [], sc)
    counter += sc.base_lore
    for uni_index in range(sc.universes):
        counter = _generate_universe(root, uni_index, base_ids, sc, counter)
    return root


# ---------------------------------------------------------------------------
# Snapshot (candidate .cache/ representation)
# ---------------------------------------------------------------------------
def index_to_payload(index, edges: dict[str, list[str]]) -> dict:
    return {
        "version": 1,
        "by_id": {
            nid: {
                "id": entry.id,
                "path": str(entry.path),
                "kind": entry.kind,
                "entry_type": entry.entry_type,
                "title": entry.title,
                "layer": entry.source_layer_label,
            }
            for nid, entry in index.by_id.items()
        },
        "edges": edges,
    }


def snapshot_dump(payload: dict, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def snapshot_load_raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_rehydrate(payload: dict) -> dict:
    """Raw dicts are not what consumers use — they read `entry.path` (a Path)
    and `entry.kind`. Rehydration is part of the honest load cost."""
    from app.services.project.node_index import NodeIndexEntry  # noqa: PLC0415

    out: dict[str, NodeIndexEntry] = {}
    for nid, raw in payload["by_id"].items():
        out[nid] = NodeIndexEntry(
            id=raw["id"],
            path=Path(raw["path"]),
            kind=raw["kind"],
            entry_type=raw["entry_type"],
            title=raw["title"],
            source_layer_id="",
            source_layer_label=raw["layer"],
        )
    return out


def build_manifest(index) -> dict[str, tuple[int, int]]:
    """path -> (mtime_ns, size); the staleness-detection stamp."""
    manifest: dict[str, tuple[int, int]] = {}
    for entry in index.by_id.values():
        try:
            stat = entry.path.stat()
        except OSError:
            continue
        manifest[str(entry.path)] = (stat.st_mtime_ns, stat.st_size)
    return manifest


def sweep_manifest(manifest: dict[str, tuple[int, int]]) -> list[str]:
    """Equality diff, not recency — restored/extracted files can carry older
    mtimes and would slip past a `newer than snapshot` test."""
    changed: list[str] = []
    for path_str, stamp in manifest.items():
        try:
            stat = Path(path_str).stat()
        except OSError:
            changed.append(path_str)
            continue
        if (stat.st_mtime_ns, stat.st_size) != stamp:
            changed.append(path_str)
    return changed


# ---------------------------------------------------------------------------
# Query strategies
# ---------------------------------------------------------------------------
def edge_list_backlinks(edge_list: list[tuple[str, str]], target: str) -> list[str]:
    return [src for src, dst in edge_list if dst == target]


def build_reverse_adjacency(edge_list: list[tuple[str, str]]) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = {}
    for src, dst in edge_list:
        reverse.setdefault(dst, []).append(src)
    return reverse


def sqlite_build(payload: dict, edge_list: list[tuple[str, str]], db_path: Path) -> int:
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(
        "CREATE TABLE nodes(id TEXT PRIMARY KEY, path TEXT, kind TEXT, entry_type TEXT, title TEXT);"
        "CREATE TABLE edges(src TEXT, dst TEXT);"
        "CREATE INDEX idx_edges_dst ON edges(dst);"
    )
    con.executemany(
        "INSERT OR REPLACE INTO nodes VALUES(?,?,?,?,?)",
        [(r["id"], r["path"], r["kind"], r["entry_type"], r["title"]) for r in payload["by_id"].values()],
    )
    con.executemany("INSERT INTO edges VALUES(?,?)", edge_list)
    con.commit()
    con.close()
    return db_path.stat().st_size


def sqlite_point_lookup(db_path: Path, sample: list[str]) -> float:
    con = sqlite3.connect(db_path)
    start = time.perf_counter()
    for nid in sample:
        con.execute("SELECT path FROM nodes WHERE id=?", (nid,)).fetchone()
    elapsed = time.perf_counter() - start
    con.close()
    return elapsed / max(1, len(sample))


def sqlite_backlinks(db_path: Path, sample: list[str]) -> float:
    con = sqlite3.connect(db_path)
    start = time.perf_counter()
    for nid in sample:
        con.execute("SELECT src FROM edges WHERE dst=?", (nid,)).fetchall()
    elapsed = time.perf_counter() - start
    con.close()
    return elapsed / max(1, len(sample))


# ---------------------------------------------------------------------------
# Measurement sections
# ---------------------------------------------------------------------------
def _measure_build(svc: ProjectService) -> tuple[float, object, float, float, dict]:
    """Three numbers, because they answer different questions (#305).

    `_build_node_index` now extracts the edges in the same front-matter pass, so
    the *projection* is what a caller holding an index pays for the graph — while
    `reference_graph()` still rebuilds the index from scratch on every call
    (memoizing that is #306/#307), so it stays the honest cost of the endpoint.
    """
    t_index, index = time_it(svc._build_node_index)
    t_project, _ = time_it(lambda: {src: [e.dst for e in edges] for src, edges in index.edges_by_src.items()})
    t_graph, graph = time_it(svc.reference_graph)
    return t_index, index, t_project, t_graph, graph.refs


def _report_footprint(index, edges: dict) -> None:
    """Size what the index actually holds.

    Earlier revisions sized `graph.refs` — the flattened `{src: [dst]}` dict —
    but since #305 that is a throwaway projection. The index holds
    `ReferenceEdge` objects in a forward map *and* a reverse one, ~3x the flat
    dict, and #306 sizes its snapshot off this number.
    """
    # Sized off `candidates` + `edges_by_layer_src` since #334: those are the
    # storage, and `by_id` / `edges_by_src` are derived views over the same
    # objects. Summing a derived view instead would undercount a chain that
    # shadows — exactly the chains #306 has to budget for.
    size_index = deep_size(index.candidates)
    size_forward = deep_size(index.edges_by_layer_src)
    size_reverse = deep_size(index.edges_by_dst)
    size_flat = deep_size(edges)
    bodies = {nid: entry.path.read_text(encoding="utf-8") for nid, entry in index.by_id.items()}
    edge_count = sum(len(e) for e in index.edges_by_layer_src.values())
    shadowed = sum(len(c) - 1 for c in index.candidates.values())
    print(f"  [Q1] index (candidates)         : {mb(size_index)}   ({len(index.by_id)} nodes, {shadowed} shadowed)")
    print(f"       edges_by_layer_src          : {mb(size_forward)}   ({edge_count} edges)")
    print(f"       + edges_by_dst (reverse)    : {mb(size_forward + size_reverse)}   <- what the index holds")
    print(f"       (flat {{src: [dst]}} for ref) : {mb(size_flat)}")
    print(f"       + every body in memory      : {mb(size_index + size_forward + size_reverse + deep_size(bodies))}")


def _report_snapshot(payload: dict, snap: Path) -> None:
    t_dump, size = time_it(snapshot_dump, payload, snap)
    t_load, raw = time_it(snapshot_load_raw, snap)
    t_rehydrate, _ = time_it(snapshot_rehydrate, raw)
    print(f"  [Q4] snapshot write            : {t_dump * 1000:8.1f} ms   (json {mb(size)})")
    print(f"       snapshot load (raw json)  : {t_load * 1000:8.1f} ms")
    print(f"       + rehydrate to NodeIndex  : {t_rehydrate * 1000:8.1f} ms")
    print(f"       = usable index            : {(t_load + t_rehydrate) * 1000:8.1f} ms")


def _report_queries(payload: dict, edges: dict, index, db: Path) -> None:
    edge_list = [(src, dst) for src, dsts in edges.items() for dst in dsts]
    sample = list(index.by_id.keys())[:: max(1, len(index.by_id) // 200)][:200]

    t_dict, _ = time_it(lambda: [index.by_id.get(nid) for nid in sample])
    t_scan, _ = time_it(lambda: [edge_list_backlinks(edge_list, nid) for nid in sample[:20]])
    t_rev_build, reverse = time_it(build_reverse_adjacency, edge_list)
    t_rev, _ = time_it(lambda: [reverse.get(nid, []) for nid in sample])

    t_db_build, db_size = time_it(sqlite_build, payload, edge_list, db)
    per_point = sqlite_point_lookup(db, sample)
    per_backlink = sqlite_backlinks(db, sample)

    print(f"  [Q7] dict id->entry            : {t_dict / len(sample) * 1e9:8.0f} ns")
    print(f"       edge-list scan backlinks  : {t_scan / 20 * 1e6:8.1f} us   ({len(edge_list)} edges)")
    print(f"       reverse-map build         : {t_rev_build * 1000:8.1f} ms")
    print(f"       reverse-map backlinks     : {t_rev / len(sample) * 1e9:8.0f} ns")
    print(f"       sqlite build              : {t_db_build * 1000:8.1f} ms   (db {mb(db_size)})")
    print(f"       sqlite id->path           : {per_point * 1e6:8.1f} us")
    print(f"       sqlite backlinks          : {per_backlink * 1e6:8.1f} us")
    db.unlink(missing_ok=True)


def _report_incremental(svc: ProjectService, index, count: int = 10) -> None:
    paths = [e.path for e in list(index.by_id.values())[:: max(1, len(index.by_id) // count)]][:count]
    schema = svc.read_metadata_schema()

    def reparse():
        return [svc._read_front_matter_only(p) for p in paths]

    t_reparse, _ = time_it(reparse)
    entries = list(index.by_id.values())[:: max(1, len(index.by_id) // count)][:count]
    t_refs, _ = time_it(lambda: [svc._reference_edges_for_entry(e, schema) for e in entries])
    print(f"  [Q6] re-parse {count} changed files : {t_reparse * 1000:8.2f} ms")
    print(f"       + re-extract their edges    : {t_refs * 1000:8.2f} ms")


def run_scale(sc: Scale, regen: bool) -> None:
    root = FIXTURE_ROOT / f"fixture_{sc.name}"
    print(f"\n{'=' * 74}\nSCALE {sc.name}  ({sc.universes} universes x {sc.books_per_universe} books)")
    if regen or not root.exists():
        print("  generating fixture ...", end="", flush=True)
        elapsed, _ = time_it(generate, sc)
        print(f" {elapsed:.1f}s")

    book = root / "universe_00" / "series_00" / "book_00"
    # Must precede the open: the bound decides how deep the chain is, and the
    # numbers below are meaningless if it is the developer's real config (#429).
    set_machine_root(root)
    # `open_project` was removed with the service singleton in #399; this bench
    # kept calling it and would have raised on the first scale.
    svc = ProjectService.opened_at(book)

    layers = svc._project_layer_folders(book)
    total_files = sum(1 for _ in root.rglob("*.md"))
    print(f"  chain depth={len(layers)}   shelf .md files={total_files}")
    if len(layers) < 4:
        # The bench exists to measure a deep chain. Reporting one-layer numbers
        # under a four-layer heading is worse than not running: it is what a
        # stale `projects_base_folder` did here for one whole release.
        raise SystemExit(f"fixture is not layered (depth={len(layers)}); regenerate with --regen")

    t_schema, _ = time_it(svc.read_metadata_schema)
    print(f"  [Q3] read_metadata_schema (uncached, {len(layers)} layers) : {t_schema * 1000:6.1f} ms")

    t_index, index, t_project, t_graph, edges = _measure_build(svc)
    edge_count = sum(len(e) for e in index.edges_by_src.values())
    print(f"  [Q2] _build_node_index   : {t_index * 1000:8.1f} ms   ({len(index.by_id)} nodes, {edge_count} edges, one pass)")
    print(f"       + project the graph : {t_project * 1000:8.1f} ms   (index in hand - no re-parse)")
    print(f"       reference_graph()   : {t_graph * 1000:8.1f} ms   (rebuilds the index; memoizing it is #306/#307)")

    _report_footprint(index, edges)

    payload = index_to_payload(index, edges)
    _report_snapshot(payload, FIXTURE_ROOT / f".snapshot_{sc.name}.json")

    t_manifest, manifest = time_it(build_manifest, index)
    t_sweep, changed = time_it(sweep_manifest, manifest)
    print(f"  [Q5] build manifest            : {t_manifest * 1000:8.1f} ms   ({len(manifest)} files)")
    print(f"       staleness sweep (clean)   : {t_sweep * 1000:8.1f} ms   ({len(changed)} divergent)")

    _report_incremental(svc, index)
    _report_queries(payload, edges, index, FIXTURE_ROOT / f".snapshot_{sc.name}.sqlite")
    (FIXTURE_ROOT / f".snapshot_{sc.name}.json").unlink(missing_ok=True)


def main() -> None:
    regen = "--regen" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    for sc in SCALES:
        if only and sc.name not in only:
            continue
        run_scale(sc, regen)
    print("\ndone.")


if __name__ == "__main__":
    main()
