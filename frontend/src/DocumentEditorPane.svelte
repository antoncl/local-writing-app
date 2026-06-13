<script lang="ts">
  import { createEventDispatcher, onMount } from "svelte";
  import { Editor } from "@tiptap/core";
  import StarterKit from "@tiptap/starter-kit";
  import Table from "@tiptap/extension-table";
  import TableCell from "@tiptap/extension-table-cell";
  import TableHeader from "@tiptap/extension-table-header";
  import TableRow from "@tiptap/extension-table-row";
  import { editorHtmlToSceneMarkdown, sceneMarkdownToHtml } from "./markdown";
  import type { Scene } from "./types";

  export let scene: Scene | null = null;
  export let dirty = false;
  export let saving = false;

  const dispatch = createEventDispatcher<{
    change: { title: string; bodyMarkdown: string };
    save: void;
    delete: void;
  }>();

  let editorElement: HTMLDivElement;
  let editor: Editor | null = null;
  let loadedSceneId: string | null = null;
  let title = "";

  $: if (editor && scene && scene.id !== loadedSceneId) {
    void loadScene(scene);
  }

  $: if (editor && !scene && loadedSceneId !== null) {
    loadedSceneId = null;
    title = "";
    editor.commands.clearContent(false);
  }

  onMount(() => {
    editor = new Editor({
      element: editorElement,
      extensions: [
        StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
        Table.configure({ resizable: true }),
        TableRow,
        TableHeader,
        TableCell,
      ],
      content: "",
      editorProps: {
        attributes: {
          class: "editor-body",
        },
      },
      onUpdate: emitChange,
    });

    if (scene) {
      void loadScene(scene);
    }

    return () => editor?.destroy();
  });

  async function loadScene(nextScene: Scene) {
    const sceneId = nextScene.id;
    title = nextScene.title;
    const html = await sceneMarkdownToHtml(nextScene.body_markdown || "");
    if (!editor || scene?.id !== sceneId) return;
    editor.commands.setContent(html || "<p></p>", false);
    loadedSceneId = sceneId;
  }

  function emitChange() {
    if (!scene || !editor) return;
    dispatch("change", {
      title,
      bodyMarkdown: editorHtmlToSceneMarkdown(editor.getHTML()),
    });
  }
</script>

<div class="editor-panel">
  <section class="editor-header">
    {#if scene}
      <input class="title-input" bind:value={title} on:input={emitChange} />
      <div class="toolbar">
        <button type="button" on:click={() => editor?.chain().focus().toggleBold().run()}>Bold</button>
        <button type="button" on:click={() => editor?.chain().focus().toggleItalic().run()}>Italic</button>
        <button type="button" on:click={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}>H2</button>
        <button type="button" on:click={() => editor?.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}>Table</button>
        <button type="button" on:click={() => dispatch("delete")}>Delete</button>
        <button class="primary" type="button" disabled={saving || !dirty} on:click={() => dispatch("save")}>
          {saving ? "Saving" : "Save"}
        </button>
      </div>
    {:else}
      <h2>Select a scene</h2>
    {/if}
  </section>
  <div class="editor-wrap" bind:this={editorElement}></div>
  <footer class="status">
    {#if scene}
      {dirty ? "Unsaved changes" : `Loaded ${scene.title}`}
    {:else}
      No scene open
    {/if}
  </footer>
</div>
