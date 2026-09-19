<script lang="ts">
  // Test-only stand-in for MetadataLongTextEditor (#642: the component-test
  // harness deliberately never mounts TipTap under happy-dom — see
  // ListValueEditor.test.ts's identical note). BodySections.test.ts swaps this
  // in via `vi.mock` so it can assert the section markup (headings, ids,
  // captions) mounts without throwing, without exercising the real editor.
  interface Props {
    value?: string;
    ariaLabel?: string;
    matcher?: unknown;
    onChange?: (value: string) => void;
    neighbours?: (() => unknown) | null;
    onEditorReady?: (editor: unknown, phase: "ready" | "destroy") => void;
  }
  let { value = "", ariaLabel = "" }: Props = $props();
</script>

<div class="mock-long-text" data-testid="mock-long-text" aria-label={ariaLabel}>{value}</div>
