# Prompt reference

Everything you can write inside a prompt: every value, call, filter and tag, and
what each one gives you back. New to prompts? Start with
**[Writing prompts](#guide:writing-prompts)**, then use this page to look things up.

The page has two layers:

- **At a glance** — the tables just below, one line per item, grouped by what you
  are trying to do. This is also what the editor shows when it completes a name.
- **[In detail](#in-detail)** — further down, one entry per item: what it does, how
  to call it, what comes back, an example, and what to watch out for.

## Three kinds of call

Almost every call does one of three things. Knowing which one you have explains
most surprises:

![Three columns. Read: entry(x).rank reads a value and you print it, the value lands in your text. Choose: use(x) prints nothing; the app adds the entry to what the AI sees, in its own place, once. Print: story_so_far(scene) prints a ready-made block of text where you write it.](diagrams/three-kinds.svg)

- **Read** a value, then print it, test it or loop over it — like `scene.title`
  or `entry(inputs.character).rank`.
- **Choose** what the AI sees — like `use()` and `auto_lore()`. These print
  nothing where you write them; the app fetches what you chose and places it,
  once, in the right spot. Write them as `{% do … %}`.
- **Print** a ready-made block of text where you write it — like
  `story_so_far(scene)`.

### In a chat, what you print is fixed at the first message

A chat renders its prompt **once**, when you send the first message, and keeps
that text for the rest of the conversation. So whatever you **read** or **print**
(`scene.body`, `scene.summary`, `story_so_far(scene)`) stays as it was then, even
if you edit the scene mid-chat. What you **choose** with `use()` is different: the
app fetches it fresh on every turn, so the AI sees your latest saved version.

For a scene the chat should keep up with, choose it instead of printing it:

```jinja
{% do use(scene) %}
```

A prompt run once from the editor renders fresh on every run, so this only
matters in a chat.

## As of this scene

A prompt runs **on one scene**, and it reads your story as it stands there. When a
lore entry changes partway through the book (a [mutation](#guide:mutations)), what
a call sees depends on *when* it looks:

![A timeline of the book from its start, through earlier scenes, across this scene, to later scenes. original(x) reads at the book's start. lore_as_of("start") places lore as this scene opens. lore_as_of("selection") places it where the selection begins. entry(x), and lore placed by default, read at the end of this scene. Later scenes are never seen.](diagrams/as-of-this-scene.svg)

- `entry(x)` — and the lore the app places — see every change up to the **end** of
  this scene.
- `original(x)` sees the entry as the book **began**, ignoring every change.
- `lore_as_of("start")` / `lore_as_of("selection")` move the lore the app places
  back to the scene's opening, or to where your selection starts.
- **Nothing ever sees a later scene.** A prompt with no scene reads the book's
  starting values.

## Variables

Values the prompt starts with. Each is described [in detail](#values) below.

| Name | What it is |
| --- | --- |
| `scene` | The scene the prompt runs on — `scene.title`, `scene.body`, `scene.<field>` — or `None`. |
| `project` | The project — `project.title`, or a project field such as `project.spelling`. |
| `inputs` | What the prompt asked you for when it ran, by name — `inputs.tone`. |
| `selection` | The selected prose (a string), or `""` when nothing is selected. |
| `text_before` / `text_after` | The prose before / after the cursor (strings), or `""` outside the editor. |
| `date` | Today's date — `date.year`, `date.month`, `date.day`. |

## Helpers

### Read your story

| Call | Gives you |
| --- | --- |
| `entry(x, at=scene, position=n)` | The entry `x` as of this scene, with its changes so far applied. |
| `original(x)` | The entry `x` as the book began, ignoring every change. |
| `fields(x)` | The list of fields an entry (or an entry type) has — label, type, group, options. |
| `field_value(entity, field)` | The value of one field — the companion to `fields()`. |
| `type_name(x)` | A type's display name, e.g. `"Character"`. |
| `is_a(node, entry_type)` | `True` if the node is of that type, or a type built on it. |
| `pov(scene)` | The scene's own POV character, or `None`. |
| `resolved_narration(scene)` | The narration the scene actually uses — `mode`, `character`, `tense` — inherited from its chapter, act or book. |
| `previous_scene(x)` | The scene before `x` in reading order, or `None`. |
| `next_scene(x)` | The scene after `x` in reading order, or `None`. |
| `scene_mutations(scene)` | The changes placed in a scene, in order — each with its target and a readable summary. |
| `todos(x)` | The open TODOs on an entry or a scene — each with `text`, `quote`, `from`. |
| `full_outline()` | The whole manuscript outline, as a nested list you loop over. |
| `full_text()` | Every scene's prose in reading order, as a list you loop over. Heavy. |

### Choose what the AI sees

These print nothing. Write them as `{% do … %}`.

| Call | Does |
| --- | --- |
| `use(node, "stable"\|"volatile", snapshot=id)` | Adds an entry (or a whole picker selection) to what the AI sees. |
| `auto_lore()` | Turns on automatic lore: what the scene links to, and the entries named in it, the prompt or your message. |
| `lore_named_in(text)` | Lists the lore entries a piece of text names — hand it to `use()`. |
| `no_lore()` | Makes the prompt lore-free: no always-include entries, no automatic lore. |
| `lore_as_of("start"\|"selection")` | Places lore as the scene opened, or where the selection starts, instead of at its end. |

### Print a ready-made block

| Call | Prints |
| --- | --- |
| `story_so_far(scene)` | A recap of every earlier scene's summary. |
| `plot_context(as_of=node, focus=card)` | The plot board up to a point, with later reveals hidden. |
| `character_turns(scene, character)` | The scene as a back-and-forth chat, for roleplay. Use it outside any `{% role %}`. |
| `roleplay_beats(scene)` | A roleplay scene laid out beat by beat, for tidying it into prose. |

### Work with text

| Call | Gives you |
| --- | --- |
| `prose(text)` | `text` with the app's markers removed — clean story text. |
| `last_words(text, n)` | The last `n` words of `text`. |
| `stop(message)` | Ends the run before anything is sent, and shows `message` to you. |

### Ask the AI to fill in fields

`field_contract` is an object you use through these three:

| Use | Does |
| --- | --- |
| `{% do field_contract.store(f) %}` | Promises the AI will fill in field `f` (a `fields()` item). |
| `{{ field_contract.render }}` | Prints the promised fields, for the AI to follow. |
| `field_contract.stored` | The promised fields — the app accepts exactly these from the reply. |

## Filters

| Filter | Gives you |
| --- | --- |
| `value \| json` | `value` as compact JSON, in its original order. |

Jinja's standard filters (`join`, `length`, `default`, `upper`, …) work as usual.

## Tags

| Tag | Does |
| --- | --- |
| `{% role "system"\|"user"\|"assistant" %}…{% endrole %}` | Sets who the wrapped text is from. Text outside any role goes to the prompt's default role. |
| `{% do … %}` | Runs a call and prints nothing — the way to write the *choose* calls. |
| `{% include "Snippet title" %}` | Inserts a snippet, found by its title. |

Jinja's standard tags (`if`, `for`, `set`, `macro`, comments `{# … #}`) work as
usual.

## Retired names

Older prompts may use these. Each now has a replacement:

| Old | Use instead |
| --- | --- |
| `base(x)` | `original(x)` |
| `entry_as_of(x, s)` | `entry(x, at=s)` |
| `effective(x, f, s)` | `entry(x, at=s).f` |
| `field_catalog` | `fields` |
| `entry_type_label` | `type_name` |
| `scenes_before` | `story_so_far` |
| `character_thread` | `character_turns` |
| `plain_json`, `tojson` | the `\| json` filter |
| `input` | `inputs` |
| `novel` | `project` |
| `relevant_lore(…)` | `auto_lore()`, or `use()` for specific entries |
| `{% cache_break %}` | nothing — the app arranges caching for you |

---

# In detail

## Values

#### scene

The scene the prompt runs on, or `None` when it runs without one (from a lore
entry, say). Read any of its fields with a dot:

```jinja
{{ scene.title }} — {{ scene.summary }}
```

- `scene.body` is the story text, with the app's markers already removed.
- **Watch out:** in a chat, a printed `scene.body` stays as it was at the first
  message. To keep up with edits, write `{% do use(scene) %}` instead
  ([why](#in-a-chat-what-you-print-is-fixed-at-the-first-message)).
- A field that points at another entry gives you that entry, so you can keep going:
  `scene.pov.title`.
- **Watch out:** check `{% if scene %}` first in a prompt that can run without one.

#### project

The project. `project.title` is always there; your own project fields
(`project.spelling`, `project.tense`, …) are there when some layer sets them — a
value set on a series reaches every book in it.

```jinja
{% if 'spelling' in project.metadata %}Use {{ project.spelling }} spelling.{% endif %}
```

- **Watch out:** reading a field nobody has set is an error, not an empty value.
  Guard it with `'name' in project.metadata`, as above.

#### inputs

What the prompt asks you for when it runs, by the names you gave them in the
prompt's setup. A text or choice input is a string; a number is a number; a
picker is a **list** of entries.

```jinja
Rewrite this in a {{ inputs.tone }} tone.
Focus on {{ entry(inputs.character).title }}.
{% do use(inputs.lore) %}
```

- `entry(inputs.character)` takes the first pick; `use(inputs.lore)` takes them all.
- An optional input the user left blank is still there, just empty: `""` for
  text, an empty list for a picker or list, and `None` for everything else — a
  yes/no, a number, a choice. So `{% if inputs.note %}` is all the guard it needs.
- A blank required input is not there at all; the app won't run the prompt
  until it's filled in.
- **Watch out — a yes/no input has three values, not two:** `True`, `False`,
  or `None` when the user left it Unset. `{% if inputs.flag %}` treats Unset as
  no. To tell "didn't choose" from "chose no", test `inputs.flag is none`.
- **Watch out — `default()` doesn't replace `None`.** `{{ inputs.length |
  default(1200) }}` prints `None` when the input is left blank; write
  `default(1200, true)`, which replaces any empty value. Don't use that on a
  yes/no input: it would replace `False` too. Write
  `{% if inputs.flag is not false %}` for "yes unless they said no".
- `{{ inputs.flag }}` on a blank input prints the word `None`.

#### selection, text_before, text_after

The prose you had selected, and the prose on either side of the cursor — all
plain strings, `""` when the prompt wasn't run from the editor.

- **Watch out:** `text_before` and `text_after` still carry the app's markers. Run
  them through [`prose()`](#prose) before showing them to the AI.

#### date

Today's date: `date.year`, `date.month`, `date.day`, or `{{ date }}` for the whole
thing.

## Reading your story

#### entry()

`entry(x, at=scene, position=n)` — an entry **as of this scene**: every change made
to it up to the end of the scene is applied. `x` is usually a picker input; it can
also be an entry (such as `scene.pov`) or an entry's id.

```jinja
{% set honor = entry(inputs.character) %}
{{ honor.title }}, {{ honor.rank }}, of {{ honor.home_place.title }}.
```

- A field that points at another entry gives you that entry — chain as far as you
  like.
- Fields you've grouped into a section can be read through the section's name:
  `honor.GMO.Goal`. If the name has a space, use brackets:
  `honor["Antagonist GMO"].Goal`. An unknown group or field reads as `None`.
- `at=` reads as of a different scene (`at=None` means the book's start);
  `position=` reads partway through a scene. You rarely need either.
- **See also:** [`original()`](#original), [As of this scene](#as-of-this-scene).

#### original()

`original(x)` — the entry as the book **began**, ignoring every change. Use it next
to `entry(x)` to show the AI what changed:

```jinja
Rank at the start: {{ original(inputs.character).rank }}
Rank now: {{ entry(inputs.character).rank }}
```

#### fields()

`fields(x)` — the list of fields an entry has, so a prompt can work for **any**
type without naming fields. `x` is an entry, or a type such as
`"lore:character"`. Each item has:

| Part | What it is |
| --- | --- |
| `id` | The field's name, as you'd write it after a dot. |
| `label` | The name the author sees. |
| `type` | The field's type: text, select, `entity_ref`, … |
| `group` | The section the field sits in, or `None`. |
| `options` / `option_labels` | For a choice field: the stored values, and the text shown for each. |
| `description` | The field's help text. |
| `proposable` | Whether the AI is meant to suggest a value for it. |

```jinja
{% for f in fields(e) if f.group == "GMO" %}
- {{ f.label }}: {{ field_value(e, f) }}
{% endfor %}
```

- To show a choice field's value the way the author sees it:
  `f.option_labels.get(v, v)`.
- A list field also has `items` (its members); a tag field the AI may suggest also
  has `tag_vocabulary` (the tags already in use, most used first).

#### field_value()

`field_value(entity, field)` — the value of one field. `field` is a field's id or an
item from `fields()`. A field that points at another entry gives you that entry;
an empty one gives `None`.

```jinja
{{ field_value(e, "patron").title }}
```

#### type_name()

`type_name(x)` — a type's display name: `type_name("lore:character")` gives
`Character`.

#### is_a()

`is_a(node, entry_type)` — `True` if the node is of that type, or of a type built on
it (a `Villain` type based on `Character` counts as a character).

```jinja
{% if is_a(e, "lore:character") %}Describe their voice.{% endif %}
```

#### pov()

`pov(scene)` — the POV character set **on the scene itself**, or `None`. A scene
that inherits its POV from its chapter or the book has none of its own here — use
[`resolved_narration()`](#resolved_narration) for the one it actually uses.

#### resolved_narration()

`resolved_narration(scene)` — the narration a scene actually uses, after
inheriting from its chapter, act and book:

| Part | What it is |
| --- | --- |
| `mode` | The point-of-view mode, or `None`. |
| `character` | The POV character, or `None` — always `None` for an omniscient or objective mode. |
| `tense` | The tense, or `None`. |

```jinja
{% set nar = resolved_narration(scene) if scene else none %}
{% if nar and nar.character %}The point-of-view character is {{ nar.character.title }}.{% endif %}
```

#### previous_scene() and next_scene()

`previous_scene(x)` / `next_scene(x)` — the scene before or after `x` in reading
order, across chapter and act breaks, or `None` at either end. `x` is a scene or a
plot card (a card counts as the scene it's attached to).

```jinja
{% set previous = previous_scene(scene) %}
{% if previous %}The last scene ended: {{ last_words(previous.body, 300) }}{% endif %}
```

#### scene_mutations()

`scene_mutations(scene)` — the changes placed in a scene, in the order they
appear. Each item has:

| Part | What it is |
| --- | --- |
| `kind` | `"change"`, or `"end"` when an earlier change stops applying. |
| `target` | The changed entry's title. |
| `entity` | The changed entry itself — hand it to `use()`. |
| `changes` | One line per field: `Rank: Lieutenant → Captain`, `Allies: + Mara`. |
| `text` | The whole change on one line: `Honor — Rank: Lieutenant → Captain`. |
| `anchor_id` | The marker's own id. |

```jinja
{% for c in scene_mutations(scene) %}
- {{ c.text }}{% do use(c.entity) %}
{% endfor %}
```

#### todos()

`todos(x)` — your open TODOs on an entry or a scene (for a scene, including the ones
marked in its prose). Each item has `text`, `quote` (the words it marks, or empty)
and `from` (the entry the app raised it from, or empty). Reading them never marks
one done.

```jinja
{% for t in todos(e) %}- {{ t.text }}
{% endfor %}
```

#### full_outline()

`full_outline()` — the manuscript's outline as a nested list. Each item has
`title`, `summary`, `level` (`"Act"`, `"Chapter"`, …; `None` for a scene) and
`children`.

```jinja
{% for act in full_outline() %}
## {{ act.title }}
{% for chapter in act.children %}- {{ chapter.title }}: {{ chapter.summary }}
{% endfor %}{% endfor %}
```

- **Watch out:** it's a list — loop over it. `{{ full_outline() }}` prints a raw
  list, not an outline.

#### full_text()

`full_text()` — every scene's prose, in reading order, as a list. Each item has
`title` and `body` (clean story text).

```jinja
{% for s in full_text() %}
## {{ s.title }}
{{ s.body }}
{% endfor %}
```

- **Watch out:** this is the whole book — very expensive. For one scene use
  `scene.body`; for a recap use [`story_so_far()`](#story_so_far).

## Choosing what the AI sees

These calls print nothing where you write them. The app collects what you chose,
fetches it, removes duplicates and places it — so the same entry is sent once, in
the spot that caches best. **[What the AI sees](#guide:ai-context)** explains what
gets placed and why.

#### use()

`use(node, hint, snapshot=id)` — adds an entry to what the AI sees. Hand it a whole
picker input to add every pick.

```jinja
{% do use(inputs.lore) %}
{% do use(scene.pov) %}
```

- **Watch out:** `use()` doesn't turn automatic lore on — add
  [`auto_lore()`](#auto_lore) for that.
- `use()` also takes a scene: `{% do use(scene) %}` sends its prose and fields.
  In a chat this is how to give the AI a scene you keep editing, because a
  printed `scene.body` stays as it was at the first message.
- The optional hint, `"stable"` or `"volatile"`, tells the app whether you expect
  the entry to change during a chat. Leave it off unless you know.
- `snapshot=` places the entry as it was at a saved snapshot, next to the live one
  if you `use()` that too.

#### auto_lore()

`auto_lore()` — turns on automatic lore. On top of what you chose, the app sends
the entries the scene links to (its POV character, its location, …) and the
entries **named** in the scene's prose, in the prompt or in your message — plus one
step out from those, fitted to the assistant's budget. Leave it out, and only what
you chose and the *always include* entries are sent.

```jinja
{% do auto_lore() %}
```

- **Watch out:** automatic lore is a chat feature. A prompt run once from the
  editor sends only what you chose and the *always include* entries, even if it
  calls `auto_lore()`.

#### lore_named_in()

`lore_named_in(text)` — the lore entries a piece of text names (by title or alias),
plus the entries those link to and the scene's own links — so a passage that only
says "she" still brings the POV character. Hand the result to `use()`:

```jinja
{% set named = lore_named_in(selection) %}
{% if not named %}{{ stop("Nothing in the selection names a lore entry.") }}{% endif %}
{% do use(named) %}
```

- Entries marked *never include* are left out; *only when picked* entries are left
  out unless the scene itself links to them.

#### no_lore()

`no_lore()` — the prompt sends no lore at all: no always-include entries and no
automatic lore. What you `use()` is still sent. If the prompt also calls
`auto_lore()`, `no_lore()` wins and the Preview warns you.

#### lore_as_of()

`lore_as_of("start")` or `lore_as_of("selection")` — places the lore as it stood
earlier in the scene, instead of at its end:

- `"start"` — as the scene opened. A **draft** wants this, so it doesn't already
  know how the scene ends.
- `"selection"` — where the selection starts (the scene's opening if nothing is
  selected). A **check** wants this, so a change later in the scene doesn't look
  like a contradiction.

```jinja
{% do lore_as_of("start") %}
```

- It affects one-off runs and the Preview; in a chat it has no effect yet.

## Printing a ready-made block

#### story_so_far()

`story_so_far(scene)` — a recap of every scene before this one, in reading order,
built from their summaries. Prints nothing when there is nothing before.

```jinja
{% if story_so_far(scene) %}
## The story so far
{{ story_so_far(scene) }}
{% endif %}
```

- It only has what your summaries say — write them, and it gets better.

#### plot_context()

`plot_context(as_of=node, focus=card)` — the plot board up to a card or scene, with
every later reveal hidden. `plot_context()` with nothing shows the whole board.

```jinja
{{ plot_context(as_of=scene) }}
{{ plot_context(as_of=next_scene(e) or e.id, focus=e.id) }}
```

- `focus` marks the card you're working on. Until that card is written into a
  scene, its synopsis is left off the board — print it yourself.
- To see one scene further, anchor on the next scene, as in the second line.

#### character_turns()

`character_turns(scene, character)` — rebuilds a roleplay scene as a chat: the
character's lines become the AI's turns, everyone else's become yours, marked
`[Name]:`.

```jinja
{% role "system" %}You are {{ entry(inputs.character).title }}.{% endrole %}
{{ character_turns(scene, inputs.character) }}
```

- **Watch out:** it makes its own roles — write it **outside** any `{% role %}`
  block.

#### roleplay_beats()

`roleplay_beats(scene)` — a roleplay scene laid out beat by beat: who speaks, what
they say and do, and their private thoughts. Use it to turn a roleplay into prose;
a scene without beats comes back as it is.

## Working with text

#### prose()

`prose(text)` — `text` with the app's markers taken out (change markers, roleplay
beats and private thoughts, TODO marks). A field such as `scene.body` is already
clean; use this on `text_before`, `text_after` and `selection`.

```jinja
{% set before = prose(text_before) %}
```

#### last_words()

`last_words(text, n)` — the last `n` words of `text`. Handy for the end of a long
passage:

```jinja
{{ last_words(before, 800) }}
```

#### stop()

`stop(message)` — ends the run before anything is sent, and shows you `message`.
Use it when the prompt can't do its job:

```jinja
{% if not scene.summary %}{{ stop("This scene has no summary yet.") }}{% endif %}
```

## Filling in fields

#### field_contract

When a prompt asks the AI to **fill in fields** — "flesh out this character" — you
promise which fields it will fill, show the AI that list, and the app then accepts
exactly those from the reply:

```jinja
{% for f in fields(e) if f.proposable %}{% do field_contract.store(f) %}{% endfor %}
Suggest values for these fields:
{{ field_contract.render }}
```

- Nothing promised means nothing is accepted.

## Formatting

#### json

`value | json` — prints `value` as compact JSON, keeping its order, with no HTML
escaping. Use it to hand the AI structured data:

```jinja
Known facts: {{ entry(inputs.character).metadata | json }}
```

A node prints as an object of everything a prompt can read from it — `id`,
`title`, `entry_type`, `metadata` and `body` — so `{{ scene | json }}` in the
preview is a quick way to see what a scene offers. That holds wherever the node
sits in what you print (alone, in a list, in a dict you built), except inside
another node: a node that a field refers to shows as just its `id` and `title`.
Both work as written — `{{ scene.pov.id }}`, `{{ scene.pov.title }}` — and
`{{ scene.pov | json }}` shows the rest. `project | json` gives the project's
`title` and `metadata`.

## Tags

#### role

`{% role "system" %}…{% endrole %}` — who the text inside is from: `system`
(standing instructions), `user` (the request) or `assistant` (the AI's own turn).
Text outside any role goes to the prompt's default — usually `system` — so a
one-message prompt needs no role at all.

- An empty role block sends nothing, so you can wrap it in an `{% if %}`.
- Roles can't be nested.

#### do

`{% do … %}` — runs a call and prints nothing. It's how you write the
[choosing](#choosing-what-the-ai-sees) calls and `field_contract.store()`.

#### include

`{% include "Project settings" %}` — inserts a snippet, found by its title. A
snippet is a prompt you can't run on its own, kept to be reused. What it prints
lands where you include it, and it sees the same values your prompt does.

That includes anything you `set` before the include. The built-in snippets that
work on a scene (*Scene brief*, *Prose generation settings*, *Character voice in
prose*) use this for one thing: which scene. Each reads `prose_scene` if your
prompt set it, and the editor's `scene` otherwise, so a prompt that works on a
scene the writer picked sets it once, before including them:

```jinja
{% set prose_scene = entry(inputs.entry) %}
{% include "Prose generation settings" %}
{% include "Scene brief" %}
```

A snippet of your own that expects a value from the prompt including it should
say so in its comment, and fall back to something sensible when the value isn't
there, so it still renders when you preview it on its own.
