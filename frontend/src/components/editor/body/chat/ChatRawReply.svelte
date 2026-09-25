<!--
  ChatRawReply — the disclosure ChatBodyView shows below a commit notice when
  the extraction's patch was unusable (garbled, or empty): the model's raw
  reply, collapsed by default, so the author can see WHAT it actually said
  without it dominating the pane (#2201).
-->
<script lang="ts">
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

  interface Props {
    text: string;
  }

  let { text }: Props = $props();
</script>

<details class="crr" data-testid="chat-raw-reply">
  <summary><GroupCaret size="xs" ambient />The model's reply</summary>
  <pre class="crr-text">{text}</pre>
</details>

<style>
  .crr {
    max-width: 82%; font-size: var(--fs-sm); color: var(--text-3);
    border: 1px solid var(--divider); border-radius: 9px; background: var(--inset); padding: 5px 11px;
  }
  .crr summary {
    display: flex; align-items: center; gap: 6px; cursor: pointer; list-style: none;
    --group-caret-open: 0deg;
  }
  .crr summary::-webkit-details-marker { display: none; }
  .crr[open] summary { --group-caret-open: 90deg; }

  .crr-text {
    white-space: pre-wrap; overflow-wrap: anywhere; max-height: 20rem; overflow: auto;
    margin: 6px 0 0; font-family: var(--mono);
  }
</style>
