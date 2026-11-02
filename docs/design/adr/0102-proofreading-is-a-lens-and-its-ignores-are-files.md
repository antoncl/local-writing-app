# ADR-0102: Proofreading is a lens, and what the writer tells it to ignore is kept in files

- **Status:** Accepted — 2026-11-02, Anton Lauridsen (PR #2654). Text by Claude from the design in
  epic #2653 and the four decisions Anton recorded there on 2026-11-02. Amendment 1 (slice 1,
  same day) corrects the span unit and adds lowercase dictionary forms.
- **Feature:** spelling and grammar feedback in the scene editor that works out of the box, stays
  on the machine, and doesn't drown a fiction writer in false positives. This ADR covers **step 1**:
  the Harper engine running in the browser. Step 2 (LanguageTool) gets its own ADR.
- **Relates to:** #2646 (the proposal and the grammar-extension audit; its story-aware checks plug
  into the pipeline in §3), #2647 (why plot cards are excluded), ADR-0039 and ADR-0042 (the layer
  chain and `inherits:`), ADR-0049 (the built-in Library: read-only, clone not fork), ADR-0056 §5
  (when a boundary earns a gate), ADR-0071 (the migration ladder), ADR-0072 (packaging), ADR-0095
  (mutation anchors are inline atoms in prose), ADR-0101 (style notes).
- **Context verified against `e6e0c9bf` (2026-11-02).** The harper.js facts were verified the same
  day against the published `harper.js@3.0.0` package (its `dist/index.d.ts`), the docs at
  `writewithharper.com/docs/harperjs/` (Introduction, Spans, Configure Rules) and the two Harper
  issues cited.
- **Words used here.** A *finding* is one problem an engine reports at a range of text. An *engine*
  produces findings (Harper here). A *layer* is one folder in the open project's chain, as
  `metadata.schema.yaml` uses the word, plus the machine layer and the built-in Library. The
  *lens* is the proofreading view the writer switches on and off.

## Context

**What the writer saw.** Anton ran a real scene through both candidate engines on 2026-11-02:

- **Harper** flagged proper names over and over: characters, places, invented words. Without a
  dictionary that knows the story's names it is unusable on fiction.
- **LanguageTool** was better, but over-eager on grammar that fiction bends on purpose: fragments,
  dialogue, a voice's own rhythm.

So the ignore model is the core of the feature, not an afterthought. The engine finds candidates;
what makes it usable is that the writer can say, once and permanently, "this is fine".

**The engine.** `harper.js` is Harper's grammar checker compiled to WebAssembly. Its package says
it "always runs on-device".

- Version 3.0.0, Apache-2.0, English only, five dialects (`Dialect`: American, British,
  Australian, Canadian, Indian).
- The docs call the package "currently in early access", meaning the API is not yet stable.
- `WorkerLinter` runs Harper in a dedicated Web Worker so linting never blocks typing.
  `LocalLinter` runs on the calling thread.
- The binary is `dist/harper_wasm_bg.wasm`, 20.4 MB. `harper.js/binary` points at it with
  `new URL(…, import.meta.url)`, so a Vite build emits it as a separate asset that is fetched only
  when the module is imported. The package also ships `binaryInlined` (the same binary as 27 MB of
  JavaScript) and a `slimBinary` (20.1 MB).
- `lint(text, options)` takes `language: 'plaintext' | 'markdown' | 'typst'` and **defaults to
  `markdown`**.
- A lint's `span()` is a start and end index into the text's **Unicode scalar values** (code
  points), per the Spans page. JavaScript strings index UTF-16 code units, so the two differ after
  any character outside the Basic Multilingual Plane, such as an emoji.
- A lint has `message()`, `lint_kind()` (a `LintKind` such as `Spelling`, `Grammar`, `Style`) and
  `suggestions()`. A suggestion has a `kind()` of `Replace`, `Remove` or `InsertAfter`, and
  `get_replacement_text()`. `applySuggestion(text, lint, suggestion)` returns the whole changed
  text.
- **The dictionary:** `importWords(words)`, `exportWords()`, `clearWords()`.
- **Rules:** `LintConfig` is a flat `Record<string, boolean | null>` keyed by rule name;
  `setLintConfig`, `getLintConfig`, `getDefaultLintConfig`. `getStructuredLintConfig()` and
  `getLintDescriptions()` are for settings UIs. The docs warn that rules are added constantly, so a
  consumer must not rely on any rule existing and must leave room for new ones.
- **Ignoring one spot:** `contextHash(source, lint)` returns a `bigint`; `ignoreLintHash(hash)`
  ignores future lints with that hash; `ignoreLint`, `exportIgnoredLints`, `importIgnoredLints` and
  `clearIgnoredLints` work on the same list.
- **All three are held in the linter's memory.** Nothing in the package persists them.
- **Harper issue #3490** (open, reported on 2.0.0): a `WorkerLinter`'s default-on rules stay
  inactive until `getDefaultLintConfig()` is called once after `setup()`; the reporter found that
  `setLintConfig` also arms them.
- **Harper issue #3875** (open): a dictionary word is still flagged with `'s` appended. The
  maintainer's answer is that the user dictionary is a bare word list with no inflection, so
  `Homer` and `Homer's` must both be listed.

**What the editor already has.** Scene prose is TipTap/ProseMirror in `ProseBodyView.svelte`. Its
overlays are decoration plugins in `frontend/src/lib/editor-core/`, registered side by side
(`ProseBodyView.svelte:1132-1135`):

- `ImplicitContextHighlight` (`implicitContextHighlight.ts:296`) marks lore names and builds the
  hover card for one (`POPUP_CLASS`, `implicitContextHighlight.ts:39`).
- `ReadAloudHighlight` (`readAloudHighlight.ts:27`) keeps the sentence being spoken as plugin state,
  maps it through edits, and draws it as one inline decoration.
- `SearchMatchHighlight` marks search hits.

The lore names are compiled once. `implicitContextMatcherStore` (`lib/stores/derived.ts:15`) runs
`compileMatcher` (`implicitContextMatcher.ts:144`) over the lore store, and the store holds the
open project's lore together with the lore it inherits. `compileMatcher` takes an entry's title and
its `aliases` (`readAliases`, `implicitContextMatcher.ts:120`), and in a scene
`createSceneEffectiveMatcher` (`sceneEffectiveMatcher.svelte.ts:17`) substitutes the names an entry
has as of that scene, so a renamed character matches under the new name. `compileMatcher` skips
entries whose context policy is `never` or `manual_only`, because its highlight promises the entry
reaches the model's context.

The prose contains two inline atom nodes, the mutation anchor and its close
(`createMutationMark`, `proseMarks.ts:157`; `createMutationCloseMark`, `proseMarks.ts:232`;
ADR-0095). Each is a point in the text with no text of its own.

**Layered files.** `metadata.schema.yaml` is the model for per-layer settings: each folder in the
chain may carry one, the merge runs outermost to nearest with nearer winning
(`_merge_metadata_schema_layer`, `services/project/schema.py:1230`), and a layer gets the file only
when something is saved there. The one walk over the chain is `visit_layers`
(`services/project/layers.py:154`). With `include_library` and `include_machine` it also yields
the built-in Library (`library_layer`, `layers.py:442`; the read-only folder
`backend/app/builtin_library/`, never a write target) and the machine layer, the machine config
dir (`machine_settings.config_dir`, `services/machine_settings.py:214`; `%APPDATA%\<app>` on
Windows). The walk yields the machine layer only when that dir holds a node-family folder
(`_machine_layer_folder`, `layers.py:498`). The packaged app ships all of the `app` package's data
files and the whole built frontend (`packaging/local-writing-app.spec:20,24`).

## Intent

The writer switches proofreading on for a revision pass, sees quiet underlines in the scene prose,
fixes what is wrong with ordinary edits, and tells the checker once, permanently and at the right
scope, what is right. Story names are never flagged. Nothing leaves the machine and nothing needs
installing.

## Anti-goals

- **Not always-on.** Proofreading is a lens for a revision pass. Underlines during a first-draft
  sprint break the flow of getting a scene onto the page (§1).
- **Not an install step**, and no Docker, in step 1 or later.
- **Not manuscript text leaving the machine.** The engine runs in the browser; its binary is served
  by the app itself.
- **Not hidden word lists or rule sets.** The fiction default is a file the writer can read, and
  every list is a file the writer can open. Nothing the writer chose lives in browser storage.
- **Not checking where it can't work well:** plot cards (the zoomed canvas, #2647), titles, ids,
  code, chat. Step 1 checks scene prose, then long-text fields (slice 3).
- **Not a prose score.** Underlines show where to look, not a grade. No counts, no summary panel.
- **Not a ProWritingAid clone.** The checks are Harper's, filtered by the writer's ignores; the
  app adds the story's names and the writer's scope, not more generic checks.
- **Not a highlight layer per engine.** One layer and one popover draw every engine's findings
  (§3).
- **Not lore names written into the dictionary file.** They are derived on every load (§5), so a
  rename never leaves a stale word behind.
- **Not ignores stored in the scene file.** An ignore is not prose and must not change the scene's
  content or revision (§6, Rejected).

## The journey that defines done

1. The writer opens a scene of a book whose world has invented names. No proofreading code or
   binary has loaded; the network panel shows no `.wasm` request.
2. The writer switches proofreading on. The control says it is loading; within a few seconds
   underlines appear in the scene. With the network disconnected, this works the same.
3. No character, place or other lore name is underlined, including an alias, a possessive
   ("Kael's", with a straight or a curly apostrophe), a name that lives in the world project
   rather than the book, and a name a mid-story rename gave a character as of this scene.
4. The writer clicks an underline. A popover shows the message and the fixes. Choosing a fix
   changes only that text: Ctrl+Z undoes it as one step, the scene saves, and a TODO anchor around
   the word survives as it does for any typed edit (#2646 audit).
5. On an invented word, the writer chooses **Add to dictionary** and picks the world layer. The
   word stops being underlined. In another book of the same world, it is not underlined either.
6. On a style rule the book breaks on purpose, the writer chooses **Stop checking this rule** for
   this project. Every finding of that rule disappears from this book and stays in another book.
7. On a deliberate fragment, the writer chooses **Ignore here**. That one underline goes. After a
   reload it is still gone. When the writer rewrites the sentence, the check runs again on the new
   text.
8. The writer switches proofreading off. The underlines go. The next app start begins with it off.
9. The writer opens the project folder and the world folder: `proofreading.yaml` in the world holds
   the word, `proofreading.yaml` in the book holds the rule, and `proofreading.ignored.yaml` in the
   book holds one hash under the scene's id.

## Decision

### 1 — A lens the writer switches on, off at every start

- **One on/off control in the scene editor's footer** (`EditorFooter.svelte`, where Read aloud's
  player already sits). It shows a quiet loading state while the engine starts.
- **The state is app-wide for the session** and not persisted: every scene's prose shows findings
  while it is on, and the app starts with it off. A revision pass is a sitting; a lens that comes
  back on by itself would put underlines on the next first draft.
- **Switching it off removes every finding** and stops linting. The worker stays loaded for the
  session, so switching on again is immediate.

### 2 — Harper, in a worker, behind one adapter, shipped in the app

- **`WorkerLinter` from `harper.js`, pinned exactly at `3.0.0`** in `frontend/package.json` (no
  caret). The API is early-access, so an upgrade is a deliberate change with its own check: the
  journey above, rerun.
- **One adapter module imports `harper.js`: `frontend/src/lib/proofread/harperEngine.ts`.** It owns
  setup, the config, the dictionary and the ignore hashes, and turns Harper's lints into findings
  (§3). Nothing else imports `harper.js`. This boundary is not gated by a fitness script: a breach
  breaks loudly at the next upgrade rather than silently corrupting data, which ADR-0056 §5 says is
  the bar for a gate.
- **The binary ships in the app and is loaded lazily.** The adapter imports `harper.js/binary`
  (the separate `.wasm` asset), and the adapter itself is loaded with a dynamic `import()` the first
  time the lens is switched on. Startup and the first-draft path never load it. The built frontend
  grows by the binary's 20.4 MB; the packaged app already ships the whole built frontend, so no
  packaging change is needed. Fetching the binary from the internet on first use was rejected: it
  breaks offline-first.
- **Setup order:** `setup()`, then `getDefaultLintConfig()` (the base for §5's merge, and the
  workaround for Harper #3490), then `setLintConfig` with the merged config, then `importWords` and
  `ignoreLintHash` for the loaded words and hashes.
- **Each text block is linted on its own**, with `language: 'plaintext'`: the editor hands Harper
  the block's text, not Markdown, and with the default `markdown` Harper would read the prose's
  own asterisks and underscores as markup. Linting is debounced after typing and cached by the
  block's text, and the cache is cleared whenever the words, rules or ignores change. A text block
  (a paragraph, a heading, a paragraph in a list or a table cell) is also the unit an ignore hash
  is computed against (§6), so changing the unit is a storage change.
- **Building a block's text:** text nodes are concatenated in order and a hard break becomes a
  newline. The mutation anchor and close atoms contribute nothing: they are points, and the text
  around them already carries its own spaces. The adapter keeps a map from each text offset to its
  document position.
- **Offsets:** Harper's span indexes code points. The adapter converts it to UTF-16 offsets into
  the block's text before anything else sees it.

### 3 — One findings pipeline, one layer, one popover

- **An engine returns findings.** A finding is
  `{engine, from, to, kind, ruleId, message, fixes[]}`:
  - `from`/`to` are UTF-16 offsets into the block text the engine was handed;
  - `kind` is the engine's category (Harper's `LintKind`);
  - a fix is `{label, from, to, insert}` in the same offsets. Harper's `Replace` replaces the span,
    `Remove` inserts the empty string over it, and `InsertAfter` inserts at the span's end.
- **One ProseMirror extension draws them:** `frontend/src/lib/editor-core/proofreadHighlight.ts`,
  registered beside `ImplicitContextHighlight` and `ReadAloudHighlight`. Like `ReadAloudHighlight`
  it keeps its state in its plugin, maps it through edits, and draws inline decorations. Spelling
  and everything else get two underline treatments, from the design tokens.
- **One popover**, opened by a click on an underline: the message, the fixes, and the ignore
  actions the engine supports (§4). It closes on Escape, on a click elsewhere and when the lens
  goes off.
- **A fix is an ordinary edit.** It is one ProseMirror transaction replacing `[from, to)` with
  `insert`, mapped from block offsets to document positions. It goes through the same path as
  typing: TipTap's update saves it, undo reverses it in one step, and marks behave as they do for
  typed text. Harper's `applySuggestion`, which returns the whole changed text, is not used: putting
  a whole block back would drop its marks and make undo coarse.
- **Other engines plug in here.** LanguageTool in step 2 and the story-aware checks from #2646
  (watched words, a character's tics) are engines that return findings. None of them gets its own
  layer or popover.
- **Wiring stays out of `ProseBodyView.svelte`**, which is at 1417 lines against the 1500 cap: the
  lens state lives in a rune controller, `frontend/src/lib/stores/proofreading.svelte.ts`, and the
  view gains one extension entry.

### 4 — Three permanent ignores, each kept at its own scope

The popover offers three ways to say "this is fine". Harper holds each only in memory, so the app
keeps all three. The frontend reads and writes them through backend endpoints (§7) and never
touches a file.

| Ignore | What it means | Harper call | Kept in | Targets offered |
|---|---|---|---|---|
| **Add to dictionary** | This word is spelled right everywhere at this level | `importWords` | `proofreading.yaml` `words`, per layer, merged down the chain | the machine, or any project layer of the chain |
| **Stop checking this rule** | This rule doesn't apply here | `setLintConfig` | `proofreading.yaml` `rules`, per layer, merged down the chain | the machine, or the open project |
| **Ignore here** | This one spot is deliberate | `contextHash` → `ignoreLintHash` | `proofreading.ignored.yaml`, per project, by node | the node |

- **Add to dictionary** lists the layers by their chain labels, outermost first. A word a world
  adds reaches every book that inherits the world, the way a field defined in the world's
  `metadata.schema.yaml` does.
- **Stop checking this rule** offers the two scopes a writer reaches for from the page. A rule set
  at another layer is set from the settings UI (slice 3), which can write any layer.
- **Ignore here** is saved in the project the node lives in, so it holds wherever that node is
  opened. The app relies on one property of Harper's hash: the same lint in an unchanged block
  hashes the same. How much surrounding text the hash covers is Harper's; editing the text near the
  spot makes the ignore lapse, and the spot is checked again.
- **An engine offers only the ignores it supports.** Harper supports all three.

### 5 — What the engine is loaded with

**Words** are the union of three sources, each expanded with its possessives (`'s` and `’s`, and a
bare `'` / `’` after a final `s`), because Harper's dictionary has no inflection (#3875):

- **The auto-dictionary.** The title and aliases of each lore entry in the lore store (the open
  project's and its inherited lore), and in a scene the names each entry has as of that scene. A
  name is split into words on whitespace and hyphens, as the matcher splits it (`SEPARATOR_RE`,
  `implicitContextMatcher.ts:47`). It is derived on every load and never saved.
  - **One extraction, two consumers.** The title-plus-aliases read moves out of `compileMatcher`
    into an exported function both use, so the matcher and the dictionary cannot disagree about an
    entry's names.
  - **No context-policy filter.** A `never` entry's name is still spelled right. The matcher's
    filter exists because its highlight promises context, which a dictionary does not.
- **The dictionary files:** `words` from `proofreading.yaml` at each layer of the chain.
- Nothing else. Harper's own curated dictionary stays as shipped.

**Rules** are merged per rule name, outermost to nearest, nearer winning:
`getDefaultLintConfig()`, then the fiction default (the Library layer's file), then the machine
layer, then the project layers from the outermost ancestor to the open project. A layer that says
nothing about a rule leaves it alone.

- **The fiction default is a visible built-in:** `backend/app/builtin_library/proofreading.yaml`,
  in the read-only Library layer (ADR-0049). It switches off rules that fight fiction; #2653 names
  `OxfordComma`, `Hedging`, `BoringWords` and `AvoidContractions` as candidates. The exact list is set by trying
  the lens on real chapters during slice 1 and is committed with slice 2. A writer who disagrees
  overrides it at the machine or a project; the Library file is never written.
- **Rule names are Harper's and may change between versions.** A name the running Harper doesn't
  know is kept in the file and skipped at load, so an upgrade never discards a writer's choice. A
  rule added by a new Harper version starts at Harper's default.

**The dialect** is a per-layer setting in the same file (`dialect`), nearest wins, American when no
layer sets it. It is set from the settings UI in slice 3.

**Ignore-here hashes** are those of the open project's `proofreading.ignored.yaml`, all of them:
Harper keeps one ignore list per linter, not one per node. An identical sentence in another node
of the project is ignored as well; identical context is the same deliberate choice.

### 6 — Storage: two optional files, absent means empty, no migration

**`proofreading.yaml`**, at any layer: a project folder of the chain, the machine config dir, or
the Library folder (read-only, shipped).

```yaml
words:
  - Vashti
  - skyglass
rules:
  OxfordComma: false
  LongSentences: true
dialect: british
```

- `words` is a list of strings, kept sorted and without duplicates on write.
- `rules` maps a Harper rule name to `true` or `false`. Setting a rule back to "as inherited"
  removes its key.
- `dialect` is one of `american`, `british`, `australian`, `canadian`, `indian`.
- An absent key is empty; an absent file is an empty file.

**`proofreading.ignored.yaml`**, in a project folder:

```yaml
ignored:
  scene_6f0c2a4e-…:
    - "11400714819323198485"
```

- Keyed by node id. Each hash is an unsigned 64-bit integer written as a decimal **string**: it crosses the HTTP API
  as JSON, where a number that large loses precision, and becomes a `bigint` in the adapter.
- A write drops keys whose node no longer exists, so a deleted scene's hashes go with the next
  ignore in that project rather than needing a hook on every delete path.
- Hashes that have lapsed because their text was edited stay until the node is deleted. They are a
  few bytes each, one per click, and Harper offers no way to tell which ones still match.

**No migration and no `CURRENT_VERSION` bump.** The migration rule exists so that a storage
*change* never relies on a defensive read. Here nothing changes shape: no existing file gains or
loses a key, and both files are new and optional. "Absent means empty" is the defined meaning of
the files, not a fallback for old data, which is how `metadata.schema.yaml` already behaves (a layer
gets one only when something is saved there). A migration could only write empty files into every
project, for no reader that needs them. An app version without this feature never reads the files,
so a project opened there loses nothing.

**Atomic writes**, like other project files. Both files are written only by the backend.

**The machine layer.** The machine `proofreading.yaml` sits in the machine config dir. The walk
yields that dir only when it holds a node-family folder, so `_machine_layer_folder` also counts the
presence of `proofreading.yaml`. Every read then goes through `visit_layers` with the Library and
the machine included, and no second derivation of the chain is added. Slice 2 checks that the node
index treats a machine layer holding only this file as empty.

### 7 — Endpoints

A thin router `backend/app/routers/proofreading.py`, logic in a `services/project/proofreading.py`
mixin on `ProjectService`, models in `backend/app/models/proofreading.py`. The intents:

- **Read the proofreading setup of the open project:** the merged words, the merged rules with the
  layer that set each, the dialect, the layers a word or rule can be written to (id and label), and
  the open project's ignore hashes by node.
- **Add a word at a layer; remove a word at a layer.**
- **Set a rule at a layer to on, off, or as inherited.**
- **Set the dialect at a layer.**
- **Ignore a spot:** a node id and a hash. The backend saves it in the project the node lives in.

A write naming the Library layer is refused, like any write to it.

## Rejected

- **Always-on quiet underlines.** They are the first-draft interruption the lens exists to avoid
  (#2646's anti-goals; Anton's decision 1 in #2653).
- **Fetching the binary on first use.** It breaks offline-first and adds a download-and-trust step
  for a file the app can ship.
- **`binaryInlined`.** The same binary as 27 MB of base64 JavaScript: larger, and parsed as script.
  `slimBinary` saves 0.3 MB and is not worth an unknown difference in behaviour.
- **`LocalLinter`.** It runs on the editor's thread, and linting a long scene would stall typing.
- **Harper's own ignore and dictionary export into browser storage.** Browser storage is per
  origin, and the dev servers' ports differ per checkout. It is invisible to the writer and is not
  a file, which breaks "files on disk are the source of truth".
- **Ignores in the scene's front matter.** An ignore would change the scene file, its save revision
  and its snapshots, for something that is not the story.
- **One machine-wide dictionary.** A world's invented words belong to the world folder, travel with
  it, and should not leak into an unrelated series.
- **Lore names written into the dictionary file.** A rename or a deleted entry would leave stale
  words. Derived names cannot go stale.
- **The matcher's compiled entries as the dictionary source.** They exclude `never` and
  `manual_only` entries, whose names are still spelled right. The shared piece is the name
  extraction, not the filtered set.
- **A migration writing empty files** (§6).
- **A rules key per engine in `proofreading.yaml` now.** How another engine's rules are kept is
  decided with that engine.

## Consequences

- A new frontend dependency, `harper.js@3.0.0`, exact. The built frontend and the packaged app grow
  by about 20 MB, loaded only when the lens is first switched on.
- A Harper upgrade can change rule names (handled, §5) and the context hash. If the hash changes,
  every ignore-here lapses once and the spots are flagged again. An upgrade PR reruns the journey
  and says which happened.
- `implicitContextMatcher.ts` exports its name extraction; `compileMatcher` and the auto-dictionary
  share it.
- `_machine_layer_folder` gains one condition (§6).
- Two new optional files can appear in a project folder and one in the machine config dir. Neither
  is a project-internal folder, so the directory picker is unaffected.

## Slices

1. **Engine and layer, no persistence.**
   - The adapter and the lazy `WorkerLinter` (§2); the findings type, the highlight extension and
     the popover in scene prose, with fixes as edits (§3); the auto-dictionary from lore (§5); the
     footer on/off control (§1).
   - Rules run at Harper's defaults; the fiction default list is chosen by using this slice on real
     chapters.
   - *Done when:* journey steps 1–4 and 8 pass, including offline, in the packaged build.
   - *Not:* any endpoint, file or ignore action; any surface but scene prose.
2. **The three ignores, saved.**
   - The two files (§6), the endpoints (§7), the machine-layer gate, the fiction default file.
   - The popover's three actions; the engine loads words, rules and hashes from the read endpoint.
   - *Done when:* journey steps 5–7 and 9 pass, and a project with neither file opens and proofreads
     as before.
   - *Not:* a settings UI; a migration.
3. **Settings and long-text fields.**
   - A settings view for rules (`getStructuredLintConfig` with `getLintDescriptions`), showing which
     layer set each rule and allowing any layer; the dialect; removing dictionary words.
   - The highlight layer in long-text fields (`MetadataLongTextEditor.svelte`, which already
     registers `ImplicitContextHighlight`).
   - *Not:* titles, ids, code, plot cards, chat.

Slices are sequential: 2 needs 1's engine, and 3 needs 2's files.

## Out of scope

- **Step 2, LanguageTool.** An optional second engine for writers who want deeper grammar
  checking, with a setup that needs no Docker. It downloads and runs a program, which needs its own
  design for checksums and trust. It gets its own ADR when step 2 starts, and plugs into §3's
  pipeline.
- **The story-aware checks of #2646.** They plug into §3 as engines. What they check and where
  their word lists live is decided in #2646.
- **Languages other than English.** Harper is English only.

## Amendment 1 — Harper's JS spans are UTF-16, the slim binary is enough, and lore names go in lower case too

2026-11-02, from running slice 1 against the real engine in the browser. It changes three
statements above and adds two facts. Nothing else changes.

### What prompted it

- **Spans.** The Context says a lint's `span()` indexes Unicode scalar values, and §2 has the
  adapter convert them to UTF-16. That came from the docs' Spans page, which describes the Rust
  core. harper.js 3.0.0 reports **UTF-16 code units**. Measured in the browser: in `a 🙂 untill b`
  and in `a 𝔸 untill b` the span of `untill` is 5–11, its UTF-16 slice; in `a é untill b` it is
  4–10. The conversion shifted every finding after an emoji by one character.
- **Binary.** §2 imports `harper.js/binary` and Rejected sets `slimBinary` aside as "an unknown
  difference". The difference is now known. With the full flavour, harper.js loads the slim binary
  as its base and the full binary on top, about 40 MB in all. The slim binary alone covers
  everything this ADR uses, checked in the browser: lints by rule (`organizedLints`), `importWords`,
  the default config (936 rules) and `setLintConfig`, `getStructuredLintConfig`,
  `getLintDescriptions`, and `contextHash` with `ignoreLintHash`. It started in under a second.
- **Case.** Harper accepts a dictionary word written with a capital only when the text has the
  capital too, while a lowercase word passes in either case. With only the lore title imported,
  `skyglass` in prose was flagged for the entry *Skyglass*.

### Decision

1. **The adapter uses Harper's span as given**, as UTF-16 offsets into the block text. The
   §2 "Offsets" bullet no longer applies. A Harper upgrade rechecks this fact along with the
   others listed under Consequences.
2. **The adapter imports `harper.js/slimBinary`**, a 20.1 MB download on first switch-on instead
   of about 40 MB.
3. **The auto-dictionary adds each word in lower case as well**, with its possessives. A lore name
   then passes whatever its case in the prose, which is how the implicit-context matcher (case-
   insensitive) already treats names. The accepted cost: a miscapitalized name (`kael`) is not
   flagged.
4. **Two facts slice 1 found, now part of the design:**
   - Vite's dev-server dependency pre-bundling moves `harper.js` without its binary, so the dev
     server answers the binary's URL with `index.html`. `frontend/vite.config.js` excludes
     `harper.js` from `optimizeDeps`. The production build is unaffected.
   - When the binary fails to load inside Harper's worker, `setup()` never settles. The lens
     limits the engine start to 60 seconds and then reports the error on the toggle, rather than
     saying "loading" forever.

### Not changed

The lens, the pipeline, the ignores and their storage, and the slices.
