<script lang="ts">
  import { onMount, tick } from "svelte";
  import NodeEditor from "../src/NodeEditor.svelte";
  import type { EntryMetadata, MetadataSchema, Scene } from "../src/types";

  let scene: Scene = {
    id: "scene-1",
    title: "Scene",
    body_markdown: "One two three.",
    revision: "initial",
    status: "draft",
    entry_type: "scene",
    metadata: { color: "Green" },
    computed_metadata: { word_count: 3 },
  };

  let metadataReload: { token: number; metadata: EntryMetadata; status: string; entryType: string } | null = null;
  let nextReloadToken = 1;
  let metadataSchema: MetadataSchema = schemaWithColor(["Red", "Green", "Blue"]);

  function schemaWithColor(options: string[]): MetadataSchema {
    return {
      version: 1,
      entry_types: {
        scene: {
          name: "Scene",
          kind: "scene",
          fields: ["status", "summary", "word_count", "color"],
        },
      },
      fields: {
        status: { name: "Status", type: "select", options: ["draft", "revised", "final"] },
        summary: { name: "Summary", type: "long_text", options: [] },
        word_count: { name: "Word Count", type: "computed", options: [] },
        color: { name: "Color", type: "select", options },
      },
    };
  }

  function schemaWithBackgroundColor(options: string[]): MetadataSchema {
    return {
      ...schemaWithColor(options),
      entry_types: {
        scene: {
          name: "Scene",
          kind: "scene",
          fields: ["status", "summary", "word_count", "background_color"],
        },
      },
      fields: {
        status: { name: "Status", type: "select", options: ["draft", "revised", "final"] },
        summary: { name: "Summary", type: "long_text", options: [] },
        word_count: { name: "Word Count", type: "computed", options: [] },
        background_color: { name: "Background Color", type: "select", options },
      },
    };
  }

  async function settle() {
    await tick();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    await tick();
  }

  function selectValue(fieldId: string) {
    const select = document.querySelector(`select[data-metadata-field-id="${fieldId}"]`) as HTMLSelectElement | null;
    return select?.value ?? null;
  }

  function reloadMetadata(metadata: EntryMetadata) {
    metadataReload = {
      token: nextReloadToken,
      metadata,
      status: "draft",
      entryType: "scene",
    };
    nextReloadToken += 1;
  }

  onMount(async () => {
    const result: Record<string, unknown> = {};
    await settle();
    document.querySelector<HTMLButtonElement>(".metadata-toggle")?.click();
    await settle();

    result.initial = selectValue("color");

    metadataSchema = schemaWithColor(["Red", "Green", "Yellow", "Blue"]);
    await settle();
    reloadMetadata({ color: "Green" });
    await settle();
    result.afterOptionInsert = selectValue("color");

    metadataSchema = schemaWithBackgroundColor(["Red", "Green", "Yellow", "Blue"]);
    await settle();
    reloadMetadata({ background_color: "Green" });
    await settle();
    result.afterRename = selectValue("background_color");

    scene = {
      ...scene,
      id: "scene-2",
      title: "Other Scene",
      metadata: {},
    };
    await settle();
    result.afterSceneWithoutValue = selectValue("background_color");

    result.pass =
      result.initial === "Green" &&
      result.afterOptionInsert === "Green" &&
      result.afterRename === "Green" &&
      result.afterSceneWithoutValue === "";
    Reflect.set(window, "__metadataSelectRegression", result);
    document.body.dataset.metadataSelectRegression = JSON.stringify(result);
  });
</script>

<NodeEditor {scene} {metadataSchema} {metadataReload} />
