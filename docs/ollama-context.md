# Ollama context

> User guide. How the app fits your local models into their context window — why a
> chat that should be light can make Ollama slow, what the app does about it, and
> the one setting worth tuning yourself. It's all automatic; the last section is
> the part you can touch.

Running a model locally through **[Ollama](https://ollama.com)** is the private,
offline heart of this app — but a local model treats its context differently from
a cloud one. Left to its defaults, a two-line question can reserve gigabytes of
memory and drag a fast machine to a crawl. Here's what's happening, and why you
mostly don't have to think about it.

## Two numbers people mix up

Almost every confusion here comes from running two different numbers together.

- **Context length** — the largest window the model was *trained* to handle. It's
  baked into the model file (Ollama reads it as `context_length`): Llama's is
  128K tokens, Qwen's 256K. A fixed ceiling. You don't set it, and it's the same
  every time you load the model.
- **`num_ctx`** — how much of that ceiling you actually *switch on* for a given
  load. Ollama reserves a working memory (its "KV cache") for exactly this many
  tokens — so **`num_ctx` is the memory cost.** Leave it unset and it fills the
  whole ceiling; size it down and you reserve only what the turn needs.

The trouble isn't the model's 128K context length — that's just its capacity.
It's that **`num_ctx` defaults to the same 128K**, whether the chat needs it or not.

## The problem: the default reserves everything

Ask a 128K model a short question and Ollama still loads it at the full 128K. The
prompt fills a sliver; the rest is empty cache holding a place for tokens that
never arrive. On a measured run, one Llama model at `num_ctx 131072` claimed about
**18 GB** and ran **76% on the CPU** — where a model runs slowly. Sized to the turn
(`num_ctx 8192`), the same model took **3.1 GB** and stayed entirely on the GPU.

<div>
<svg viewBox="0 0 860 300" role="img" aria-label="Default: 131072 tokens, about 18 GB, 76 percent on the CPU. Fitted: sized to the turn, about 4 GB, fully on the GPU."><style>.l{font-family:var(--sans)}.m{font-family:var(--mono)}.n{font-family:var(--mono);font-variant-numeric:tabular-nums}</style>
<text x="0" y="14" class="l" font-size="15" fill="var(--text)" font-weight="600">Default — load at the trained max</text>
<text x="0" y="34" class="m" font-size="12" fill="var(--text-3)">num_ctx 131072</text>
<rect x="0" y="50" width="812" height="30" rx="6" fill="var(--inset)" stroke="var(--border)"/>
<rect x="0" y="50" width="18" height="30" rx="6" fill="var(--accent)"/>
<rect x="22" y="56" width="786" height="18" rx="4" fill="none" stroke="var(--border-strong)" stroke-dasharray="4 4"/>
<text x="36" y="69" class="m" font-size="11" fill="var(--text-3)">reserved, empty cache — the rest of 131072 tokens</text>
<rect x="0" y="92" width="812" height="10" rx="5" fill="var(--inset)"/>
<rect x="0" y="92" width="617" height="10" rx="5" fill="var(--danger)"/>
<rect x="619" y="92" width="193" height="10" rx="5" fill="var(--warn)" opacity="0.5"/>
<text x="0" y="126" class="n" font-size="13" fill="var(--danger)" font-weight="600">~18 GB</text>
<text x="92" y="126" class="l" font-size="12.5" fill="var(--text-2)">76% spills to the CPU → the model crawls</text>
<line x1="0" y1="156" x2="812" y2="156" stroke="var(--border)"/>
<text x="0" y="186" class="l" font-size="15" fill="var(--text)" font-weight="600">Fitted — size to the turn</text>
<text x="0" y="206" class="m" font-size="12" fill="var(--text-3)">num_ctx 16384</text>
<rect x="0" y="222" width="812" height="30" rx="6" fill="var(--inset)" stroke="var(--border)"/>
<rect x="0" y="222" width="101" height="30" rx="6" fill="var(--accent)"/>
<text x="113" y="241" class="m" font-size="11" fill="var(--text-3)">prompt + reply, rounded to a stable step</text>
<rect x="0" y="264" width="812" height="8" rx="4" fill="var(--inset)"/>
<rect x="0" y="264" width="176" height="8" rx="4" fill="var(--accent)"/>
<text x="188" y="272" class="n" font-size="12" fill="var(--accent-strong)" font-weight="600">~4 GB · 100% GPU</text>
</svg>
</div>

It's worth being clear: this isn't the model getting *cut off*. Nothing is lost.
It's an empty reservation the size of the whole trained window, sitting in memory
your machine can't spare.

## What the app does about it

Every Ollama turn goes through four steps. The first three are automatic for every
local assistant; the fourth is a switch you flip when a chat runs long.

1. **Discover** the model's real trained window, read from its file — no cost, no
   loading the model to find out.
2. **Size** `num_ctx` to the turn: the prompt plus room for the reply, rounded up
   to a stable step, and never above the model's window.
3. **Clamp the reply**: a local reply is capped at a sensible length by default
   (about 8K tokens, not 32K), so the reservation stays small.
4. **Window the history** (optional): keep a long conversation from pushing your
   most important context out of the window.

Rounding to a step matters: changing `num_ctx` makes Ollama reload the model, so a
size that drifted token-by-token would reload it every message. Snapping to a step
means the size only changes when a chat crosses a boundary — a few reloads over a
long session instead of one per turn. A typical turn lands around **16K**,
comfortably on the GPU.

## The history window: keep the system prompt, drop old turns

This is the one to understand, because it prevents a quiet, expensive failure.

A conversation grows every turn. Eventually it outgrows even the sized window, and
something has to give. Ollama's own answer is to **truncate from the front** — and
the front is exactly where your system prompt and lore sit. The model silently
loses the instructions and world you gave it, with no warning.

The history window flips which end gives. It drops the **oldest whole exchanges**
instead, keeping the system prompt, the lore, and your current message intact.

<div>
<svg viewBox="0 0 860 330" role="img" aria-label="Without a window, an overflowing history makes Ollama drop the system prompt and lore from the front. With the history window, the oldest exchanges are dropped instead and the system prompt and lore survive."><style>.l{font-family:var(--sans)}.m{font-family:var(--mono)}</style>
<text x="0" y="14" class="l" font-size="13.5" fill="var(--danger)" font-weight="600">Without a window</text>
<text x="0" y="32" class="m" font-size="10.5" fill="var(--text-3)">Ollama truncates from the front</text>
<rect x="0" y="44" width="380" height="250" rx="8" fill="var(--inset)" stroke="var(--border)"/>
<rect x="16" y="54" width="348" height="30" rx="5" fill="var(--surface)" stroke="var(--danger)" stroke-dasharray="4 3"/>
<text x="28" y="73" class="l" font-size="11.5" fill="var(--danger)">System prompt — lost</text>
<rect x="16" y="90" width="348" height="28" rx="5" fill="var(--surface)" stroke="var(--border-strong)"/>
<text x="28" y="108" class="l" font-size="11.5" fill="var(--text-2)">Lore — partly lost</text>
<rect x="16" y="126" width="348" height="94" rx="5" fill="var(--accent-soft)" stroke="var(--border-strong)"/>
<text x="28" y="150" class="l" font-size="11.5" fill="var(--text)">Conversation history</text>
<text x="28" y="170" class="m" font-size="10.5" fill="var(--text-3)">grown past the window</text>
<rect x="16" y="228" width="348" height="30" rx="5" fill="var(--surface)" stroke="var(--border-strong)"/>
<text x="28" y="247" class="l" font-size="11.5" fill="var(--text-2)">Reply headroom</text>
<text x="460" y="14" class="l" font-size="13.5" fill="var(--accent-strong)" font-weight="600">With the history window</text>
<text x="460" y="32" class="m" font-size="10.5" fill="var(--text-3)">the app drops the oldest exchanges</text>
<rect x="460" y="44" width="380" height="250" rx="8" fill="var(--inset)" stroke="var(--border)"/>
<rect x="476" y="54" width="348" height="30" rx="5" fill="var(--accent-soft)" stroke="var(--accent)"/>
<text x="488" y="73" class="l" font-size="11.5" fill="var(--accent-strong)" font-weight="600">System prompt — kept</text>
<rect x="476" y="90" width="348" height="28" rx="5" fill="var(--accent-soft)" stroke="var(--accent)"/>
<text x="488" y="108" class="l" font-size="11.5" fill="var(--accent-strong)">Lore — kept</text>
<rect x="476" y="126" width="348" height="26" rx="5" fill="var(--surface)" stroke="var(--danger)" stroke-dasharray="4 3"/>
<text x="488" y="143" class="l" font-size="10.5" fill="var(--danger)">✂ oldest exchanges dropped</text>
<rect x="476" y="158" width="348" height="60" rx="5" fill="var(--accent-soft)" stroke="var(--border-strong)"/>
<text x="488" y="182" class="l" font-size="11.5" fill="var(--text)">Recent turns — kept whole</text>
<text x="488" y="202" class="m" font-size="10.5" fill="var(--text-3)">+ your current message</text>
<rect x="476" y="228" width="348" height="30" rx="5" fill="var(--surface)" stroke="var(--border-strong)"/>
<text x="488" y="247" class="l" font-size="11.5" fill="var(--text-2)">Reply headroom</text>
</svg>
</div>

You turn it on per assistant, with the **History budget (tokens)** field. Leave it
**blank** and nothing changes — the whole conversation is sent, exactly as before.
Set a token cap and the oldest exchanges are dropped first; a question is never
split from its answer, and your current message is always sent. When a send drops
older turns, the assistant's reply shows a quiet note — *"history 12.4k/16k · 3
earlier exchanges dropped"* — so the model's memory never shortens silently.

## Tuning it yourself

Almost all of the above is automatic. Three levers are yours when you want them —
two on each assistant, one on Ollama itself.

- **Max output tokens** (on the assistant) — how long a single reply may run.
  Defaults to a generous scene (~8K tokens); raise it if you want longer replies
  in one turn, and the window grows to fit. Blank uses the default.
- **History budget (tokens)** (on the assistant) — the history window above. Blank
  sends the whole conversation; a number caps it, protecting the system prompt and
  lore. Reach for it once a chat runs long on a small local model.
- **The KV cache precision** (on Ollama) — right-sizing changes *how many* tokens
  the cache holds; this changes *how many bytes each token costs*. By default it's
  16-bit. Dropping it to 8-bit halves the cache, at a quality cost most people
  can't detect. It's an Ollama **server** setting — an environment variable where
  you launch `ollama serve`, not a field in the app:

```
# recommended — halves the KV cache, near-invisible quality cost
OLLAMA_KV_CACHE_TYPE=q8_0  ollama serve

# aggressive — quarters it, but lossier; worst on high-GQA models like Qwen
OLLAMA_KV_CACHE_TYPE=q4_0  ollama serve
```

Sizing is the big lever; precision is the fine one. Moving a chat from 128K down to
8–32K is what gets you off the CPU in the first place — the app does that for you.
Quantizing the cache then roughly halves what's left, and it matters most at large
contexts, where the cache is actually full.

<div>
<svg viewBox="0 0 860 320" role="img" aria-label="VRAM used versus context size. At 8K and 32K the model stays around 3 to 5 GB, on the GPU. At 128K the 16-bit cache reaches about 18 GB and spills to the CPU, while the 8-bit cache stays near 10 GB, under a 12 GB example ceiling."><style>.l{font-family:var(--sans)}.n{font-family:var(--mono);font-variant-numeric:tabular-nums}</style>
<line x1="70" y1="20" x2="70" y2="250" stroke="var(--border-strong)"/>
<line x1="70" y1="250" x2="820" y2="250" stroke="var(--border-strong)"/>
<text x="60" y="254" class="n" font-size="11" fill="var(--text-3)" text-anchor="end">0</text>
<text x="60" y="200" class="n" font-size="11" fill="var(--text-3)" text-anchor="end">5</text>
<text x="60" y="145" class="n" font-size="11" fill="var(--text-3)" text-anchor="end">10</text>
<text x="60" y="90" class="n" font-size="11" fill="var(--text-3)" text-anchor="end">15</text>
<text x="60" y="45" class="n" font-size="11" fill="var(--text-3)" text-anchor="end">18</text>
<line x1="70" y1="113" x2="820" y2="113" stroke="var(--warn)" stroke-dasharray="2 5"/>
<text x="78" y="108" class="l" font-size="10.5" fill="var(--warn)">GPU memory (12 GB example)</text>
<text x="24" y="140" class="l" font-size="11" fill="var(--text-2)" transform="rotate(-90 24 140)" text-anchor="middle">VRAM used (GB)</text>
<rect x="150" y="215.6" width="34" height="34.4" rx="3" fill="var(--accent)"/>
<rect x="188" y="219" width="34" height="31" rx="3" fill="var(--accent)" opacity="0.5"/>
<text x="186" y="268" class="n" font-size="12" fill="var(--text)" text-anchor="middle" font-weight="600">8K</text>
<text x="167" y="208" class="n" font-size="10" fill="var(--text-2)" text-anchor="middle">3.1</text>
<text x="205" y="211" class="n" font-size="10" fill="var(--text-3)" text-anchor="middle">2.7</text>
<rect x="360" y="188" width="34" height="62" rx="3" fill="var(--accent)"/>
<rect x="398" y="203.3" width="34" height="46.7" rx="3" fill="var(--accent)" opacity="0.5"/>
<text x="396" y="268" class="n" font-size="12" fill="var(--text)" text-anchor="middle" font-weight="600">32K</text>
<text x="377" y="180" class="n" font-size="10" fill="var(--text-2)" text-anchor="middle">~5.5</text>
<text x="415" y="195" class="n" font-size="10" fill="var(--text-3)" text-anchor="middle">4.1</text>
<rect x="600" y="45" width="34" height="205" rx="3" fill="var(--danger)"/>
<rect x="638" y="136.2" width="34" height="113.8" rx="3" fill="var(--accent)" opacity="0.5"/>
<text x="636" y="268" class="n" font-size="12" fill="var(--text)" text-anchor="middle" font-weight="600">128K</text>
<text x="617" y="38" class="n" font-size="10" fill="var(--danger)" text-anchor="middle" font-weight="600">~18</text>
<text x="655" y="128" class="n" font-size="10" fill="var(--text-3)" text-anchor="middle">~10</text>
<text x="617" y="235" class="l" font-size="9.5" fill="#fff" text-anchor="middle" transform="rotate(-90 617 235)">spills to CPU</text>
<rect x="150" y="288" width="14" height="14" rx="3" fill="var(--accent)"/>
<text x="172" y="299" class="l" font-size="11" fill="var(--text-2)">16-bit cache (default)</text>
<rect x="360" y="288" width="14" height="14" rx="3" fill="var(--accent)" opacity="0.5"/>
<text x="382" y="299" class="l" font-size="11" fill="var(--text-2)">8-bit cache (q8_0)</text>
<rect x="600" y="288" width="14" height="14" rx="3" fill="var(--danger)"/>
<text x="622" y="299" class="l" font-size="11" fill="var(--text-2)">over the ceiling → CPU</text>
</svg>
</div>

The figures above are measured on a Llama-family model; your exact numbers vary by
hardware and architecture. The shape is what holds: right-sizing keeps you on the
GPU, and 8-bit precision buys headroom at the top end.

---

Provider setup lives in **[Turning on AI](#guide:ai-setup)**; how the app chooses
what world and history to send is **[Context picker](#guide:context-picker)**.
