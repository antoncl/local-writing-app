<script lang="ts">
  import { onMount, tick } from "svelte";
  import DocumentEditorPane from "../src/DocumentEditorPane.svelte";
  import type { LoreEntry, MetadataSchema } from "../src/types";

  let entry: LoreEntry = {
    id: "lore-1",
    title: "Robert Smith",
    body_markdown: "Known as Bob in private notes.",
    revision: "initial",
    entry_type: "lore_note",
    metadata: { tags: [] },
    computed_metadata: {},
  };

  let metadataSchema: MetadataSchema = {
    version: 1,
    entry_types: {
      lore_note: {
        name: "Note",
        kind: "lore",
        fields: ["tags"],
      },
    },
    fields: {
      tags: { name: "Tags", type: "tags", options: [] },
    },
  };

  async function settle() {
    await tick();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await tick();
  }

  onMount(async () => {
    const result: Record<string, unknown> = {};
    await settle();
    document.querySelector<HTMLButtonElement>(".tag-picker-toggle")?.click();
    await settle();

    result.initialTags = Array.from(document.querySelectorAll<HTMLButtonElement>(".tag-picker button")).map((button) => button.textContent);
    result.pass = JSON.stringify(result.initialTags) === JSON.stringify(["Crew", "Magic"]);
    Reflect.set(window, "__knownTagsRegression", result);
    document.body.dataset.knownTagsRegression = JSON.stringify(result);
  });
</script>

<DocumentEditorPane scene={entry} documentKind="lore" {metadataSchema} knownTags={["Crew", "Magic"]} />
