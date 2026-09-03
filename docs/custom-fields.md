# Custom fields

> User guide. How to add your own fields to Entries — what a field is, and how to
> pick the right **type** (and, for lists, the right **item shape**) without
> needing to know anything technical.

Every Entry in your Lore — a character, a location, an item — can carry
**fields**: the pieces of information you want to keep about it. A character's
age, a location's ruler, whether a faction has been introduced yet. The app
comes with a few fields, and you add your own in **Custom Data**.

Each field has three things: a **name** (what you call it), a **type** (what kind
of value it holds), and a few options. Picking the type is the only choice that
ever feels technical — so this guide is mostly about that. The short version:
**decide what you're recording, and the type follows.**

## What are you recording?

Find the row that matches, and use that type. The names in **bold** are exactly
what you'll see in the type picker.

- A short word or phrase — an epithet, a ruler's name → **Text**
- A longer passage — an appearance, a backstory → **Long Text**
- A quantity — an age, a population → **Number**
- A simple yes or no — *introduced?*, *still alive?* → **Checkbox**
- A colour to tint the Entry in lists and on boards → **Colour**
- **One** choice from a set you decide — a status of *Alive / Dead / Missing* → **Select**
- **Several** choices from a set you decide — roles from *Protagonist / Ally / Villain* → **Select, Multiple**
- Loose labels you invent as you go and reuse for filtering — themes, moods →
  **Entry Reference, Multiple**, sourced from **Tags** (see below)
- A link to **one** other Entry — a character's home → **Entry Reference**
- Links to **several** other Entries — a character's allies → **Entry Reference, Multiple**
- A growing list you keep adding to — aliases, goals, relationships → **List**
- A value the app works out for you — a word count → **Computed**

If two of these feel interchangeable, the next two sections pull the confusing
ones apart.

## Quick reference

| Type | Use it when you want… | Example on a character |
| --- | --- | --- |
| **Text** | a short line of words | "Epithet": *the Grey* |
| **Long Text** | a paragraph or more | "Appearance" |
| **Number** | a quantity you might compare or total | "Age": *34* |
| **Checkbox** | a yes/no flag | "Introduced?" |
| **Colour** | a swatch to tint the Entry | the character's colour on the board |
| **Select** | one option from a fixed set | "Status": *Alive* |
| **Select, Multiple** | several options from a fixed set | "Roles": *Ally*, *Comic relief* |
| **Entry Reference** | a link to one other Entry | "Home" → a location |
| **Entry Reference, Multiple** | links to several Entries | "Allies" → other characters |
| **List** | a list you keep adding to, in order | "Aliases", "Goals" |
| **Computed** | a value the app fills in | "Word count" |

## Select, a Tags reference list, and List — telling the "list-like" types apart

Several types can all look like "a list of things." The difference is *where the
choices come from* and *whether the list grows*:

- **Select** and **Select, Multiple** both draw from a **fixed set of options you
  define once** on the field. The only difference is how many you may pick:
  **Select** is exactly one, **Select, Multiple** several. Reach for these when the
  choices are known and shared — a status, a set of roles, the factions in your
  world. When you define the field you also write the options (and can give each
  a colour).
- A **Tags reference list** — an **Entry Reference, Multiple** field sourced from
  **Tags** — has **no fixed set**: pick from tags that already exist, and if the
  name you type matches nothing, tick **Offer to create a new entry when the
  typed name matches nothing** and the picker mints it on the spot, right there in
  the field. That's exactly what the built-in **Tags** field is; you can also
  source a field from a tag type of your own (a **vocabulary**, defined under the
  Tag kind in Custom Data) to keep a second, separate set of labels. Reach for
  this when you want to sprinkle loose, evolving labels across many Entries and
  filter by them later, without committing to a list of allowed values up front.
- **List** is for a collection that **keeps growing and whose order
  matters** — a character's aliases in the order they were used, a plotline's
  beats in sequence. Unlike the Select types it isn't a pick-from-options control;
  it's a list you add items to freely. And its items can be more than single
  values — see the next section.

A quick way to choose: *Is there a fixed set of allowed values?* If yes and you
pick one, **Select**; if yes and you pick several, **Select, Multiple**. If the
labels are open-ended, an **Entry Reference, Multiple** sourced from **Tags**. If
it's an open, ordered collection you build up over time, **List**.

## Lists and their item shape

When you choose **List**, the app asks one more question: **what is each
item?** You answer it once, with the *Items are…* dropdown, and there are two
kinds of answer.

**A single value.** Each item is one simple value, all of the same type — a list
of **Text** aliases, a list of **Number** measurements, a list of **Select**
choices. Pick this when every item is just one thing.

**A group.** Each item is a small bundle of several sub-fields that belong
together. A character's *relationships*, where each item has a *person*, a
*kind*, and *notes*. A plotline's *beats*, where each has a *goal*, a
*motivation*, and an *obstacle*. Pick this when a single value can't capture one
item — you need a few pieces per entry.

Groups are defined **once**, under **Groups**, and reused — so the same shape
(say, Goal / Motivation / Obstacle) can back a List here and be applied
elsewhere without redrawing it each time. In the *Items are…* dropdown your
existing groups appear together, above the single-value options. If a group
isn't offered, it's because one of its sub-fields is a type that can't sit inside
a list yet (a Select, Multiple or a Computed field, for instance — a link to
another Entry, single or multiple, is fine inside a group).

You can't leave the item shape unset — a list has to know what its items are
before you can save it.

## Names, descriptions, and defaults

A few more options round out a field, and none of them are technical:

- **Description** — a sentence on what the field is for. Worth writing: it reminds
  *you* later, and it's given to the AI when it brainstorms or drafts the Entry,
  so a clear description leads to better suggestions.
- **AI may write this field** — a toggle for whether the AI is allowed to fill the
  field in for you. Turn it off for anything you'd rather own by hand.
- **Section** — an optional heading that groups related fields together in the
  Entry's panel, so a long list of fields stays tidy.
- **Default for new entries** — an optional starting value every new Entry of this
  type begins with, so you're not filling the same thing in each time. Applies to
  value fields (Text, Number, Select, and the like); a reference field — an Entry
  Reference or a Tags field — has no default, since there's no id you could type
  in ahead of time.

## A note on Computed fields

**Computed** fields are filled in by the app, not by you — a word count, a
counter, a running cost. When you choose Computed you pick *what* to calculate
from a short menu; you never write a formula, and the field is read-only. If you
just want to record a number yourself, use **Number** instead.

## Fields change over the story

Defining a field sets what it *can* hold — not a value frozen for all time. Any
field can take a different value partway through the manuscript (a character's
status changing mid-scene, an alliance forming), and the story remembers the
change from that point forward. You don't declare any of that when you define the
field; it's a separate authoring feature. See **[Mid-scene lore changes
(mutations)](mutations.md)**.

## See also

- **[Mid-scene lore changes (mutations)](mutations.md)** — recording how a field's
  value changes as the story unfolds.
- **[Editing `metadata.schema.yaml` by hand](schema-yaml-howto.md)** — for power
  users who want to do things the Custom Data editor doesn't cover yet.
