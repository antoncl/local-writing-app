import { describe, expect, it } from "vitest";
import { sceneMarkdownToHtml } from "@/lib/utils/markdown";
import {
  escapeMarkdown,
  itemMarkdown,
  itemTitle,
  memberDisplayText,
  orderMarkdown,
  titleMemberKey,
} from "@/lib/utils/listReviewText";
import type { GroupMember, MetadataFieldDefinition } from "@/lib/types";

// ADR-0096 §6/S3: text is BUILT, not passed through, so a title that happens
// to look like markdown syntax renders as literal text once it goes through
// `renderDiffRuns`/`sceneMarkdownToHtml` — that's what these pin, rendering
// through the real markdown pipeline rather than trusting the escaping alone.

async function renders(markdown: string): Promise<string> {
  const html = await sceneMarkdownToHtml(markdown);
  return html
    .replace(/^<p>|<\/p>\n?$/g, "")
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/&amp;/g, "&")
    .trim();
}

describe("escapeMarkdown", () => {
  it.each([
    "1. Setup",
    "# x",
    "*x*",
    "- x",
    "> x",
    "[x](y)",
    "<b>",
  ])("renders %s as literal text", async (text) => {
    const rendered = await renders(escapeMarkdown(text));
    expect(rendered).toBe(text);
  });
});

const textMember: GroupMember = { key: "title", name: "Title", type: "text" };
const boolMember: GroupMember = { key: "required", name: "Required", type: "boolean", default: true };
const selectMember: GroupMember = {
  key: "mood",
  name: "Mood",
  type: "select",
  options: [{ value: "grim", label: "Grim" }],
};
const idMember: GroupMember = { key: "id", name: "Id", type: "text" };
const proseMember: GroupMember = { key: "guidance", name: "Guidance", type: "long_text" };

const groupField: MetadataFieldDefinition = {
  name: "Beats",
  type: "list",
  options: [],
  item_members: [idMember, textMember, boolMember, selectMember, proseMember],
  item_identity: "id",
} as unknown as MetadataFieldDefinition;

const scalarField: MetadataFieldDefinition = {
  name: "Rumours",
  type: "list",
  options: [],
  item_scalar: true,
  item_members: [{ key: "value", name: "Value", type: "text" }],
} as unknown as MetadataFieldDefinition;

describe("titleMemberKey / itemTitle", () => {
  it("picks the first visible text member as the title member", () => {
    expect(titleMemberKey(groupField)).toBe("title");
  });

  it("a scalar list has no title member — it is titled by its own value", () => {
    expect(titleMemberKey(scalarField)).toBeNull();
    expect(itemTitle(scalarField, "a rumour", 0)).toBe("a rumour");
  });

  it("falls back to positional naming absent a value", () => {
    expect(itemTitle(groupField, { id: "beat_1" }, 2)).toBe("Item 3");
  });

  it("reads the title member's value when present", () => {
    expect(itemTitle(groupField, { id: "beat_1", title: "Midpoint" }, 0)).toBe("Midpoint");
  });
});

describe("memberDisplayText", () => {
  it("applies the member default to an absent value", () => {
    expect(memberDisplayText(boolMember, undefined)).toBe("Yes");
    expect(memberDisplayText(boolMember, null)).toBe("Yes");
  });

  it("renders a boolean as Yes/No", () => {
    expect(memberDisplayText(boolMember, false)).toBe("No");
  });

  it("renders a select's option label", () => {
    expect(memberDisplayText(selectMember, "grim")).toBe("Grim");
  });

  it("falls back to the raw value for an unknown option", () => {
    expect(memberDisplayText(selectMember, "unknown")).toBe("unknown");
  });

  it("resolves an entity_ref through resolveTitle, falling back to the id", async () => {
    const ref: GroupMember = { key: "who", name: "Who", type: "entity_ref" };
    expect(memberDisplayText(ref, "lore_1", (id) => (id === "lore_1" ? "Mara" : null))).toBe("Mara");
    expect(await renders(memberDisplayText(ref, "lore_2", () => null))).toBe("lore_2");
  });

  it("reads empty as an em dash", () => {
    expect(memberDisplayText(textMember, "")).toBe("—");
    expect(memberDisplayText(textMember, null)).toBe("—");
  });

  it("escapes a value that looks like markdown syntax", async () => {
    const text = memberDisplayText(textMember, "1. Setup");
    expect(await renders(text)).toBe("1. Setup");
  });
});

describe("itemMarkdown", () => {
  it("renders a scalar item as its title alone", () => {
    expect(itemMarkdown(scalarField, "a rumour", 0)).toBe("**a rumour**");
  });

  it("renders the title bold, then each non-empty non-title member under its name", () => {
    const md = itemMarkdown(groupField, { id: "beat_1", title: "Midpoint", required: false, mood: "grim" }, 0);
    expect(md).toBe("**Midpoint**\n\n*Required*\n\nNo\n\n*Mood*\n\nGrim");
  });

  it("skips a blank member (raw, before any default) and the identity member", () => {
    // Every other member is absent on this item, so — like `comparisonString`
    // — nothing but the title renders; a member's default only fills in
    // display text for a member that DOES show (an edited/paired item's unit).
    const md = itemMarkdown(groupField, { id: "beat_1", title: "Aftermath" }, 0);
    expect(md).toBe("**Aftermath**");
  });

  it("renders a long_text member as its own markdown, unescaped", () => {
    const md = itemMarkdown(groupField, { id: "beat_1", title: "Midpoint", guidance: "she *wavers*" }, 0);
    expect(md).toContain("*Guidance*\n\nshe *wavers*");
  });
});

describe("orderMarkdown", () => {
  it("numbers escaped titles", async () => {
    const md = orderMarkdown(["Setup", "1. Weird Title"]);
    expect(md).toBe("1. Setup\n2. 1\\. Weird Title");
    const html = await sceneMarkdownToHtml(md);
    expect(html).toContain("Setup");
    expect(html).toContain("1. Weird Title");
  });
});
