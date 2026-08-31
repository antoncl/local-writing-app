# Writing prompts

A **prompt** is the instruction the app sends to the AI on your behalf — to
continue a scene, brainstorm a character, summarize what happened so far. You
write prompts as small templates: mostly plain text, with a few blanks the app
fills in from your story.

This guide walks through how to write one. It teaches the ideas with worked
examples; for the exhaustive list of every variable and helper, see the prompt
**[reference](#guide:reference)**.

## The three pieces

A prompt is ordinary text with two kinds of blank:

- `{{ … }}` **inserts a value** — `{{ scene.title }}` drops in the scene's title.
- `{% … %}` **runs an instruction** — a *tag*, like marking who is speaking.

Everything else is sent verbatim. So the simplest possible prompt is just:

```jinja
Continue the scene in the same voice. Do not summarize.
```

## Who's speaking: roles

A message to the AI has a *role* — `system` (standing instructions), `user`
(the request), or `assistant` (the AI's turn). Wrap text in `{% role %}` to set
it:

```jinja
{% role "system" %}
You are a co-writer for a Western novel. Match the author's prose.
{% endrole %}
{% role "user" %}
Continue from here:

{{ scene.body }}
{% endrole %}
```

You don't have to role everything — un-roled prose is treated as the prompt's
default role (usually `system`), so a plain instruction just works.

## What you can reach

A prompt runs **as of one scene** — "the story as it stands here." From that
anchor you have:

| You have | It is |
| --- | --- |
| `scene` | The scene the prompt runs on. `scene.title`, `scene.body`, `scene.pov`, `scene.summary`, and any field you've defined. |
| `project` | The project. `project.title`, and authored fields like `project.spelling`. |
| `inputs` | Anything the prompt asks *you* for (see [Inputs](#inputs), below). |
| `selection` | The prose you had selected, when the prompt was run on a selection. |
| `text_before` / `text_after` | The prose on either side of your cursor. |
| `date` | Today's date. |

## Reading your story's data

Every node — a scene, a character, a location — has **fields** determined by its
type (you define these in the [Custom fields](#guide:custom-fields) guide). Read
them with a dot:

```jinja
{{ scene.pov.title }} is the POV character; the summary is: {{ scene.summary }}.
```

To reach a node that isn't the current scene, name it with `entry(…)`:

```jinja
{{ entry("honor").goal }}
```

`entry(x)` gives you the node **as it is at this scene** — mutations that have
happened by now are applied. If you want the node as it began, ignoring every
later change, use `original(x)`. A reference field resolves to its target, so
you can chain: `{{ entry("honor").home_place.title }}`.

### Looping over fields

When a template should work for *any* type — a generic "describe this entity"
prompt — don't hard-code field names. Ask for the fields and walk them:

```jinja
{% for f in fields(entry(inputs.subject)) %}
- {{ f.label }}: {{ field_value(entry(inputs.subject), f) }}
{% endfor %}
```

`fields(x)` lists a node's field descriptors (each has a `label`, `type`,
`group`, …); `field_value(node, f)` reads one field's value. Fields you've
grouped into a section are also reachable by that section's name —
`entry(x).GMO.Goal` reads the `Goal` field inside the `GMO` group.

## Pulling in context

You rarely paste your whole world into a prompt by hand. Instead you *select*
what the model should see and let the app place it:

- `{% do use(entry("honor")) %}` — "also include Honor in the context." The app
  adds the node, deduplicates, and orders it; your template emits nothing.
- `{% do use_lore() %}` — let the app add the scene's relevant lore for you.

Some ready-made context blocks are emitted directly:

- `{{ story_so_far(scene) }}` — a recap of earlier scenes' summaries.
- `{{ full_outline() }}` — the manuscript outline (titles + summaries).
- `{{ full_text() }}` — every scene's prose (heavy — a last resort).
- `{{ plot_context(as_of=scene) }}` — the plot board up to this point, with
  later reveals hidden.

## Inputs

An input is a value the prompt asks *you* for when it runs — a tone, a target
character, a number. Declare inputs in the prompt's Setup, then read them:

```jinja
{% role "user" %}
Rewrite the passage in a {{ inputs.tone }} tone.
{{ selection }}
{% endrole %}
```

An input that picks a node resolves to that node, so combine it with `entry`:

```jinja
Focus on {{ entry(inputs.character).title }}'s motivations.
```

## Producing fields back

Some prompts ask the model to *fill in* fields — a "flesh out this character"
brainstorm. Declare the fields you want back with the **field contract**, and
show the model their shape:

```jinja
{% for f in fields(entry(inputs.character)) if f.proposable %}
  {% do field_contract.store(f) %}
{% endfor %}
Propose values for these fields:
{{ field_contract.render }}
```

The app reads the stored contract back to know exactly which fields to accept
from the model's reply — you declare the shape once and it's enforced.

## Worked example: a summarize-scene prompt

```jinja
{% role "system" %}
Summarize the scene in two sentences. Neutral, no spoilers for later scenes.
{% endrole %}
{% role "user" %}
POV: {{ scene.pov.title }}

{{ scene.body }}
{% endrole %}
```

## Formatting values for the model

When you hand the model structured data, `| json` renders it cleanly (order
preserved, no surprise escaping):

```jinja
Known facts: {{ entry(inputs.character).metadata | json }}
```

## Reusing pieces

Common fragments live as **snippets** — include one by id:

```jinja
{% include "Project settings" %}
```

## Grouping prompts into menus

When you have more than a handful of prompts, the picker gets long. A `/` in a
prompt's **title** organizes it into a submenu — so name related prompts with a
shared prefix and they fold together:

| Title | Menu |
| --- | --- |
| `Revise / Tone` | **Revise** ▸ Tone |
| `Revise / Length` | **Revise** ▸ Length |
| `Summarize` | Summarize |

Picking `Revise` opens a submenu of `Tone` and `Length`; `Summarize`, with no
`/`, stays a plain top-level item.

A few things worth knowing:

- **Spaces around the `/` don't matter** — `Revise / Tone` and `Revise/Tone` are
  the same. Nest as deep as you like: `Draft / Scene / Action`.
- **It's opt-in.** A title with no `/` is just a normal item, so nothing changes
  until you start using it.
- **A group never doubles as a prompt.** If you have both `Revise` and
  `Revise/Tone`, the plain `Revise` becomes an item *inside* the Revise group —
  so one click never both runs a prompt and opens a submenu.
- It's **purely how the name is displayed** in the menu — the title is what you
  typed, and grouping changes nothing else about the prompt.

The same menu is used wherever you pick a prompt — the chat prompt chip and the
**＋ New** conversation menu on an entry.

## Where to look next

- The prompt **[reference](#guide:reference)** — every variable, helper, filter,
  and tag with its exact shape.
- Your prompt's **Preview** tab shows the assembled messages (and their token
  cost) as you edit — the fastest way to see what a change does.
