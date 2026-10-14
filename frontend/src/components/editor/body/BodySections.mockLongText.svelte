<script lang="ts">
  // Test-only stand-in for MetadataLongTextEditor (#642: the component-test
  // harness deliberately never mounts TipTap under happy-dom — see
  // ListValueEditor.test.ts's identical note). BodySections.test.ts swaps this
  // in via `vi.mock` so it can assert the section markup (headings, ids,
  // captions) mounts without throwing, without exercising the real editor.
  // The hidden emit button stands in for typing: clicking it calls `onChange`
  // with "edited", so a test can assert what an edit writes (#2483).
  interface Props {
    value?: string;
    ariaLabel?: string;
    matcher?: unknown;
    onChange?: (value: string) => void;
    neighbours?: (() => unknown) | null;
    onEditorReady?: (editor: unknown, phase: "ready" | "destroy") => void;
  }
  let { value = "", ariaLabel = "", onChange }: Props = $props();
</script>

<div class="mock-long-text" data-testid="mock-long-text" aria-label={ariaLabel}>{value}</div>
<button type="button" hidden data-testid="mock-long-text-emit" aria-label="Emit edit" onclick={() => onChange?.("edited")}></button>
