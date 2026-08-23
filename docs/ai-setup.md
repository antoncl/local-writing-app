# Turning on AI

AI in this app is **off until you turn it on**, and even then it's a tool you point
at your prose, not a service that runs on its own. You choose the provider — a
cloud model, or a local one through [Ollama](https://ollama.com) with the network
switched off — and you see the cost of every call. This guide gets it set up.

Turning AI on is two deliberate steps, plus an optional third:

1. **Set a policy** — permission for a project to reach AI at all.
2. **Add a provider** — the API key (or local host) the models run through.
3. **Hire assistants** — optional named "who runs this" configurations.

Once those are done, you drive the AI through prompts, chats, and roleplay — each
its own guide (**[Writing prompts](#guide:writing-prompts)**,
**[Context picker](#guide:context-picker)**, **[Roleplay](#guide:roleplay)**).

## Step 1 — Set the policy

Policy is the permission layer. It fails closed: nothing reaches a provider unless
a policy allows it, and widening access is always an explicit save.

**For a project:** open the project (its own window), then click **AI Policy**. The
**AI access** dialog offers:

- **Inherit** — take the policy from a parent project, or **Off** at the top of the
  chain.
- **Off** — no AI at all.
- **Local only** — only local models (Ollama); nothing leaves your machine.
- **Cloud allowed** — cloud providers permitted (Anthropic, OpenAI, OpenRouter).

Pick one and click **Save** — a selection alone never takes effect until you do.

**App-wide default:** in **≡ menu → Settings… → AI**, the **Default AI access**
section sets the policy a project falls back to when it states none of its own. It
has its own **Apply** button, so raising the floor is a separate, deliberate act.

## Step 2 — Add a provider

Open **≡ menu → Settings… → AI**.

**Cloud providers** — under the provider list, click **+ Add provider**, choose
**Anthropic**, **OpenAI**, or **OpenRouter**, paste its **API key**, and **Save**.
Configured providers show as chips; you can rotate a key or remove one later. Keys
are stored in per-machine config, never in your project files — so a project folder
is safe to share.

> The app never asks you to type a key anywhere but here, and keys are masked on
> read. If you'd rather not use the cloud at all, skip straight to Ollama.

**Local models (Ollama)** — set the **Ollama host** field (default
`http://127.0.0.1:11434`). With Ollama running and a project policy of **Local
only**, the whole app works offline.

**Check it works** — the **Connection** section has a **Test connection** button.
If it's disabled, it tells you why (e.g. *"This project's AI access is off, so there
is nothing to reach."*).

## Step 3 — Hire an assistant

Why *assistant*, and why *hire*? Because that's the role the app gives AI — a
helper you keep beside your desk, not a faceless engine. You **subscribe** to a
provider (that was Step 2), then **hire** an assistant: give it a name and a model
and point your work at it. It's the app's whole stance in a word — a research
assistant and a sparring partner next to your manuscript, never a ghostwriter that
owns it. The vocabulary is deliberate: you staff your book, rather than configure a
model.

So an **assistant** is, concretely, a reusable "who runs this" — a name paired with
a **provider** and a **model**. Instead of choosing a model for every call, you set
up an assistant once and point work at it.

- **Create one** from **≡ menu → Assistants** (a project must be open) with the
  pane's **+** button. The create-project wizard also offers this up front, under
  **Assistants for this book → + Hire an assistant…**.
- **Choose its model** in the assistant's **Details** rail: pick a **Subscription**
  (provider), then a **Capability** tier — **⚡ Fast**, **⚖ Balanced**, **✨
  Premium**, **🧠 Reasoning**, or **💻 Local** (Ollama) — and, under **Advanced**,
  an exact **Model** if you want to pin one.
- **Curate the roster** — the Assistants pane lists your assistants (each showing
  its provider · model); **List** / **Un-list** and drag to order them. The topmost
  is the default.

Thinking in tiers rather than exact model names means you can say "use a fast model
here, a premium one there" and let each provider's current best fill the slot.

## What it costs

Every AI call is metered. Costs show in the editor as you work — per call and as a
running **project total** — so nothing is hidden. (Amounts display in euros.) The
per-character and per-scene breakdowns are covered in the **[Roleplay](#guide:roleplay)**
guide.

## You're set

With a policy, a provider, and at least one assistant, AI is ready. From here:

- **[Writing prompts](#guide:writing-prompts)** — the templates that turn your
  project into structured requests.
- **[Context picker](#guide:context-picker)** — hand a prompt exactly the scenes
  and lore it should see.
- **[Roleplay](#guide:roleplay)** — let characters take turns in a scene.

AI stays off everywhere you don't switch it on, sees only the context you give it,
and — with Ollama — never has to touch the network at all.
