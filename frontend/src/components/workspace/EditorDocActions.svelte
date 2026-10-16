<script lang="ts">
  // The action strip of an editor-document tab (project Validate / AI Policy,
  // Promote, Propagate, Delete). Split out of App.svelte (#2528); the modals and
  // their open-flags stay in App, reached through the callbacks.
  import PromoteAction from "@/components/dialogs/PromoteAction.svelte";
  import PropagateAction from "@/components/dialogs/PropagateAction.svelte";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { projectLayerIdStore } from "@/lib/stores/schema";

  let {
    id,
    onValidate,
    onOpenAiPolicy,
  }: {
    id: string;
    onValidate: () => void;
    onOpenAiPolicy: () => void;
  } = $props();

  const editorPane = $derived(editorPanes.panes.find((pane) => pane.id === id));

  // Noun for the pane's delete button, keyed by document kind (was a
  // scene/lore-only ternary that mislabelled view/prompt/chat panes).
  const PANE_DELETE_NOUN: Record<string, string> = {
    lore: "entry",
    research: "note",
    prompt: "prompt",
    assistant: "assistant",
    chat: "chat",
    view: "view",
    plot_template: "template",
    plot_card: "card",
    plotline: "plotline",
    plot_deck: "deck",
  };
  const paneDeleteNoun = (type: string | undefined) => (type && PANE_DELETE_NOUN[type]) || "scene";
</script>

{#if editorPane}
  {#if editorPane.document?.type === "project"}
    <!-- Project-only actions, re-homed from the (vanishing) Project pane to
         the project window (#417). AI Policy is fails-closed (the modal owns
         the explicit Save; this button only opens it); Validate opens the
         result modal and kicks off a fresh check. -->
    <button
      class="pin-button"
      type="button"
      title="Check this project's files for problems"
      aria-label="Validate project"
      onmousedown={(event) => event.stopPropagation()}
      onclick={onValidate}
    >
      Validate
    </button>
    <button
      class="pin-button"
      type="button"
      title="Set this project's AI access policy"
      aria-label="AI policy"
      onmousedown={(event) => event.stopPropagation()}
      onclick={onOpenAiPolicy}
    >
      AI Policy
    </button>
  {/if}
  <PromoteAction documentKind={editorPane.document?.type} entry={editorPane.scene} ownLayerId={$projectLayerIdStore} />
  <PropagateAction documentKind={editorPane.document?.type} entry={editorPane.scene} />
  <!-- The project node is its own window; deleting it would remove
       `project.md` (#750). Offer Delete on every other kind, never on the
       project itself — belt to the requestDeleteScene guard's braces. -->
  <button
    class="pin-button danger"
    type="button"
    disabled={!editorPane.scene || editorPane.document?.type === "project"}
    title={`Delete this ${paneDeleteNoun(editorPane.document?.type)}`}
    onmousedown={(event) => event.stopPropagation()}
    onclick={() => editorPanes.requestDeleteScene(editorPane.id)}
  >
    Delete
  </button>
{/if}
