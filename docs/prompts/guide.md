# Writing prompts

A **prompt** is the instruction the app sends to the AI for you: continue this
scene, tighten this paragraph, flesh out this character. Every prompt the app
ships with is one you can open and read — and you can write your own.

A prompt is mostly plain text. Where it needs something from your story, it uses a
blank the app fills in. This guide builds up from a one-line prompt to a complete
one, a step at a time. Each step adds one idea; you can stop wherever you have what
you need. When you want the exact details of something, the
**[Prompt reference](#guide:reference)** lists everything.

## Your first prompt

Open **≡ menu → Prompts**, click **+**, and pick a type under **New prompt**. The
prompt opens with three tabs:

- **Template** — what you write. This guide is about this tab.
- **Preview** — exactly what will be sent, and what it will cost, updated as you
  type. Keep it open; it's the quickest way to see what a change does.
- **Setup** — where the prompt is offered, what it asks you for, and what happens
  to the reply.

Now type a prompt. The simplest one is just an instruction:

```jinja
Continue the scene in the same voice. Do not summarize.
```

Everything you type is sent as it is. That's a working prompt — it just can't see
your story yet.

## Blanks: `{{ }}` and `{% %}`

There are two kinds of blank, and they're the whole language:

- `{{ … }}` **puts a value into the text** — `{{ scene.title }}` becomes the
  scene's title.
- `{% … %}` **does something** and leaves no text behind — a choice, a loop, a
  setting.

```jinja
Continue "{{ scene.title }}" in the same voice.

{{ scene.body }}
```

Now the AI gets the scene. Behind the scenes this is
[Jinja](https://jinja.palletsprojects.com/), a common template language, so
`{% if %}`, `{% for %}` and `{% set %}` work the way its documentation describes.

> If a name is mistyped — `{{ scnee.title }}` — the prompt stops with an error rather
> than quietly sending nothing. The Preview shows the error.

## Who's speaking: roles

The AI doesn't receive one long text. It receives a short conversation of
**messages**, and each message has a **role**:

- **system** — the standing instructions: who to be, which rules to follow, what's
  true in your world.
- **user** — the request: the passage, the question, the thing to work on.
- **assistant** — the AI's own turn: an earlier reply, or an example of the
  answer you want.

![A template on the left with a system block and a user block. Arrows lead to two messages on the right: a system message holding the instructions and the lore the app chose, and a user message holding the request and the scene. Unmarked text joins the system message.](diagrams/template-to-messages.svg)

Text you don't mark goes to the prompt's default role — usually `system` — so a
one-message prompt needs nothing more. When you want the instructions and the
request apart, wrap each in `{% role %}`:

```jinja
{% role "system" %}
You are a co-writer on a Western. Match the author's prose.
{% endrole %}
{% role "user" %}
Continue from here:

{{ scene.body }}
{% endrole %}
```

Keeping the instructions in `system` also saves money: the parts of a prompt that
don't change from run to run are sent first, so the provider can reuse them
cheaply. The app arranges that for you.

## Reading your story

From the scene, you can reach the rest of your story:

| Write | You get |
| --- | --- |
| `scene` | The scene the prompt runs on: `scene.title`, `scene.body`, `scene.summary`, and any field you've added. |
| `project` | The project: `project.title`, and project fields such as `project.spelling`. |
| `entry(inputs.character)` | An entry you picked when the prompt ran (see [Asking for input](#asking-for-input)). |
| `selection` | The text you had selected. |
| `text_before`, `text_after` | The text on either side of the cursor. |

Every entry has the fields its type gives it — you design those in
**[Custom fields](#guide:custom-fields)**. Read one with a dot. A field that points
at another entry takes you to it, so you can keep going:

```jinja
{% set honor = entry(inputs.character) %}
{{ honor.title }} serves aboard {{ honor.ship.title }}.
```

### As of this scene

Lore can change partway through your book — a promotion, a betrayal, a lost arm
(see **[Mutations](#guide:mutations)**). A prompt reads your story **as it stands
at this scene**: the changes up to here are applied, and nothing from later scenes
leaks in. When you want an entry as the book began, use `original()`:

![A timeline of the book from its start, through earlier scenes, across this scene, to later scenes. original(x) reads at the book's start. lore_as_of("start") places lore as this scene opens. lore_as_of("selection") places it where the selection begins. entry(x), and lore placed by default, read at the end of this scene. Later scenes are never seen.](diagrams/as-of-this-scene.svg)

```jinja
{{ honor.title }} began the book as a {{ original(honor).rank }}
and is now a {{ honor.rank }}.
```

## Asking for input

An **input** is something the prompt asks you for each time it runs — a tone, a
character, a length. Add inputs on the **Setup** tab, then read them by name:

```jinja
{% role "user" %}
Rewrite this in a {{ inputs.tone }} tone, in about {{ inputs.length }} words:

{{ selection }}
{% endrole %}
```

An input that picks entries gives you a list of them: `entry(inputs.character)`
takes the first, and `use(inputs.lore)` (next section) takes them all.

## Choosing what the AI sees

The AI knows only what you send it. You could paste your whole world into every
prompt, but that's slow, costly, and buries what matters. Instead you **choose**,
and the app does the sending:

```jinja
{% do use(inputs.lore) %}
{% do use(scene.pov) %}
{% do auto_lore() %}
```

- `use(x)` adds an entry — or every entry in a picker — to what the AI sees.
- `auto_lore()` lets the app add what the scene needs: the entries it links to and
  the ones it names.

These calls **print nothing** where you write them — that's why they sit in
`{% do %}`. The app gathers everything you chose, sends each entry once, and puts
it where it caches best. That's the difference between the three kinds of call
you'll meet:

![Three columns. Read: entry(x).rank reads a value and you print it, the value lands in your text. Choose: use(x) prints nothing; the app adds the entry to what the AI sees, in its own place, once. Print: story_so_far(scene) prints a ready-made block of text where you write it.](diagrams/three-kinds.svg)

What the app adds for `auto_lore()`, and how it keeps a big world within budget,
is its own guide: **[What the AI sees](#guide:ai-context)**.

## Ready-made blocks

Some context is common enough that the app builds it for you. These print a block
of text where you write them:

```jinja
{% if story_so_far(scene) %}
## The story so far
{{ story_so_far(scene) }}
{% endif %}
```

- `story_so_far(scene)` — a recap of every earlier scene, from their summaries.
- `plot_context(as_of=scene)` — the plot board up to here, later reveals hidden.
- `character_turns(scene, character)` — a roleplay scene as a back-and-forth chat
  (see **[Roleplay](#guide:roleplay)**).

The `{% if %}` around `story_so_far` skips the heading on the first scene, where
there is no story so far yet.

## Stopping early

When a prompt can't do its job — no summary to draft from, nothing selected — say
so, instead of sending the AI an empty request:

```jinja
{% if not scene.summary %}
{{ stop("This scene has no summary yet. Write one, then run Draft again.") }}
{% endif %}
```

`stop()` ends the run before anything is sent and shows you the message.

## Reusing pieces: snippets

Instructions you want in many prompts — your house style, the project's spelling
and tense — belong in a **snippet**: a prompt you can't run on its own, kept to be
included in others. Include one by its title:

```jinja
{% role "system" %}
You are a line editor.
{% include "Project settings" %}
{% endrole %}
```

The snippet's text lands where you include it, and it can use the same blanks your
prompt can. Change the snippet once, and every prompt that includes it follows.

## Asking the AI to fill in fields

A prompt can ask the AI to **fill in fields** — "flesh out this character" —
instead of writing prose. You promise which fields it will fill, show it the list,
and the app accepts exactly those from the reply:

```jinja
{% set e = entry(inputs.character) %}
{% for f in fields(e) if f.proposable %}{% do field_contract.store(f) %}{% endfor %}
Suggest values for these fields of {{ e.title }}:
{{ field_contract.render }}
```

`fields(e)` lists the entry's fields, so the same prompt works for a character, a
place or a faction without naming a single field.

## Putting it together

Here is a complete prompt that summarizes a scene. Every line is something this
guide has covered:

```jinja
{% if not scene or not scene.body.strip() %}
{{ stop("This scene is empty — write something first.") }}
{% endif %}
{% set nar = resolved_narration(scene) %}
{% role "system" %}
Summarize the scene in two or three sentences: what happens, who is in it, how it
ends. Neutral and factual; no commentary.
{% include "Project settings" %}
{% endrole %}
{% role "user" %}
{% do auto_lore() %}
{% if nar.character %}The point-of-view character is {{ nar.character.title }}.{% endif %}

{{ scene.body }}
{% endrole %}
```

`resolved_narration(scene)` is the scene's point of view and tense — set on the
scene, or inherited from its chapter or book. The reference has it, and everything
else, **[in detail](#guide:reference)**.

## Organizing prompts into menus

A `/` in a prompt's title files it in a submenu, so related prompts fold together:

| Title | In the menu |
| --- | --- |
| `Revise / Tone` | **Revise** ▸ Tone |
| `Revise / Length` | **Revise** ▸ Length |
| `Summarize` | Summarize |

- Spaces around the `/` don't matter, and you can nest as deep as you like:
  `Draft / Scene / Action`.
- A group never doubles as a prompt: with both `Revise` and `Revise / Tone`, the
  plain `Revise` moves *inside* the Revise group.
- It only changes how the title is shown — nothing else about the prompt.

The same menu appears wherever you pick a prompt: the chat's prompt chip and an
entry's **＋ New** conversation menu.

## Where to go next

- **[Prompt reference](#guide:reference)** — every value, call and tag, one entry
  each.
- **[What the AI sees](#guide:ai-context)** — what `auto_lore()` adds and how the
  app keeps it within budget.
- **[Context picker](#guide:context-picker)** — giving a prompt exactly the scenes
  and lore you choose.
- The built-in prompts — open any of them in **≡ menu → Prompts**. They are written
  to be read, and they use only what this guide and the reference describe.
