# Getting started

Welcome. This guide walks you from an empty window to a project with a scene you've
written, a character in your lore, and — if you want it — AI switched on. Ten
minutes, start to finish. You don't need to read it all at once; each section
stands alone.

A few things worth knowing up front:

- **Your work is just files.** Every scene is a Markdown file, every lore entry
  another, plus a handful of small YAML files for structure. You can read, back
  up, and version-control the whole project without this app.
- **AI is off until you turn it on**, and even then it only ever sees context you
  authored. Skip the AI section entirely if you'd rather write unassisted.
- **Nothing phones home.** There's no account and no sync — the app is two local
  processes talking to each other on your own machine.

## Create your first project

When the app opens with nothing loaded, you'll see a short line pointing you at the
**project switcher** — the button in the top-right corner. Click it and choose
**New project…** to open the **New Project** wizard.

The wizard has a few steps; you can go **Back** at any point:

1. **Projects folder** — the first time only, pick the one folder that will be
   your *library*: the single home under which all your projects live. You set
   this once. (It's also the boundary for inheritance later, so projects in the
   same library can share world-building; for now, just choose where your writing
   should live.)
2. **Location** — despite the name, this is where you name and place *this*
   project. Enter a **Project name**, then confirm the **Location** — the folder
   for this one project, normally created inside your Projects folder (use
   **Browse…** to put it elsewhere). Note that these are two different things: the
   *Projects folder* is your whole library; the *Location* is the single project
   inside it. The wizard spells out the final path under *"Will be created at:"*.
   Under **Inherit from**, a brand-new project will usually say *"Nothing to
   inherit from here — this project stands alone."* That's exactly right for your
   first book; inheritance is for later, when you build a series or a shared
   universe.
3. **AI** — leave this **Off** for now (you can turn it on any time). We'll come
   back to it below.
4. **Review** and **Describe** — glance over the defaults, add an optional
   description, and click **Create**.

To reopen a project later, use the same switcher: pick a **Recent** row, or choose
**Open folder…**.

## Find your way around

Two controls drive the whole app:

- The **≡ menu** (top-left) opens everything: your **Project** settings, **Detail
  Types**, **Prompts**, **Chats**, **Assistants**, **Plot** tools, **Mutations**,
  **Settings…**, and — under **Help** — these **Guides**.
- The **project switcher** (top-right) opens, creates, and switches projects.

The main working area is a set of panes you can drag, resize, and tile however you
like. Three are always available: **Draft** (your manuscript), **Lore**, and
**Research**. Others open from the ≡ menu when you need them.

## Write your first scene

Your manuscript lives in the **Draft** pane, under a **Scenes** heading. A fresh
project starts empty (*"No scenes yet."*).

1. Click the **+** button at the top of the pane. A small menu (**Add at root**)
   lists the kinds of node you can add — typically **Act**, **Chapter**, and
   **Scene**. Add an **Act**, then use the **+** on that row (**Add child**) to add
   a **Chapter**, and a **Scene** under that.
2. Click the scene to open it. The body is a normal what-you-see-is-what-you-get
   editor — just start typing.
3. Type **`/`** anywhere to open the command menu: headings and paragraphs under
   **Structure**, lists and quotes under **Formatting**, and **Scene break**,
   **Table**, and **Mutate lore** under **Insert**.

Alongside the prose, a **Details** panel shows the scene's fields — things like
**Summary**, **Status**, and **POV**. Which fields appear depends on your
project's schema, which you're free to shape (see **Custom fields**, below).

## Add a character (or any lore)

**Lore** is where your world lives — characters, places, factions, objects, and
anything else worth remembering. Each item is an **Entry**.

1. In the **Lore** pane, click **+** (*Add entry*).
2. The **New entry** menu lists the types your project defines (Character,
   Location, and so on). Pick one — it opens a new entry with a title, a Markdown
   body, and fields for tags and references.
3. Write who or what it is. Lore entries link to each other and are what the AI
   draws on when you ask it about your story.

> Tip: if AI is on, the **Brainstorm new…** option can draft an entry with you
> instead of starting from a blank page.

## Shape your own fields

The **Summary / Status / POV** fields on scenes are just a starting point. You can
add your own fields and even your own node types — a *POV character* reference on
scenes, a *danger level* on locations, whatever your book needs. Open the **≡ menu
→ Detail Types** to do it.

This is a topic of its own — the **[Custom fields](#guide:custom-fields)** guide
walks through it.

## See your work through Views

Every list in the app is backed by a **view** — a small query that decides what
appears and how it's grouped. Beside a pane's **+** button, the **▤ ▾** switcher
lets you pick a built-in view, choose one you've saved, or select **New view…** to
build one in the visual designer.

You can get a long way on the built-in views; reach for the designer when you want
something like "all scenes where the POV character is Honor, grouped by status."

## Turn on AI (optional)

AI is opt-in per project, in two parts:

1. **Set the project's policy.** Open **≡ menu → Project**, then **AI Policy**.
   Choose **Local only** (models on your own machine, via Ollama) or **Cloud
   allowed** (Anthropic, OpenAI, OpenRouter). Leave it **Off** to keep AI
   disabled entirely.
2. **Add your provider details.** Open **≡ menu → Settings…** and go to the **AI**
   tab. Add API keys for any cloud providers you'll use, or point the app at your
   Ollama host for local models.

Once AI is on, you drive it with **prompts** — Jinja templates you can read and
edit — and **chats** bound to those prompts. Two good next reads:

- **[Writing prompts](#guide:writing-prompts)** — how prompts work and how to
  write your own.
- **[Context picker](#guide:context-picker)** — how to hand a prompt exactly the
  scenes and lore it should know about.

## Where to go next

You now have the shape of it: a manuscript in **Draft**, a world in **Lore**, and
fields you control. When you're ready to go deeper, the other guides pick up from
here:

- **[Custom fields](#guide:custom-fields)** — design your own node types and
  fields.
- **[Mutations](#guide:mutations)** — let a fact change partway through the story,
  so earlier scenes never leak what happens later.
- **[Roleplay](#guide:roleplay)** — have characters take turns in a scene, each in
  their own voice.
- **[Writing prompts](#guide:writing-prompts)** and
  **[Context picker](#guide:context-picker)** — get the most out of AI.

Everything you write is on your disk, in plain files, the whole time. Enjoy the
quiet.
