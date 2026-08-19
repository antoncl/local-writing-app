<script lang="ts">
  // Shared input control for a PromptInputDefinition. Renders the
  // type-specific element (text / long_text / number / boolean / select /
  // entity_ref / entity_ref_list) and emits a `change` event with the new
  // value as a string. Used by both the inputs-dialog (prompt-dispatch flow)
  // and the prompt-preview inputs panel — keeps look-and-feel identical and
  // halves the maintenance surface for input types.
  import NodePicker from "@/components/widgets/NodePicker.svelte";
  import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import type {
    NodePickerConfig,
    NodePickerRef,
    LoreEntrySummary,
    MetadataFieldDefinition,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "@/lib/types";

  let {
    input,
    value,
    excludeId = null,
    ariaLabel = undefined,
    // Data sources for the context_pick input type. Optional — the picker
    // will degrade to "no items" when missing rather than throw.
    structure = null,
    // Research tree (sibling to manuscript) — threaded to the picker.
    researchStructure = null,
    loreEntries = [],
    promptEntries = [],
    // Optional matcher pass-through for implicit-context highlighting on
    // long_text inputs. Other input types ignore it.
    implicitContextMatcher = null,
    // Emitted with the new value as a string (was a `change` CustomEvent before
    // the runes pass); the inputs-dialog / prompt-preview panel persist it.
    onChange = () => {},
  }: {
    input: PromptInputDefinition;
    value: string;
    excludeId?: string | null;
    ariaLabel?: string | undefined;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    onChange?: (value: string) => void;
  } = $props();

  function refStubField(): MetadataFieldDefinition {
    // entity_ref / entity_ref_list inputs persist their picker config as a
    // NodePickerConfig under `target` (post-#40). ReferencePicker reads it
    // via `picker_config`, the same shape used on the field side. A scene_ref
    // (#60) is a single scene reference — always constrained to scenes, so it
    // borrows the single-ref widget with a fixed `{ kinds: ["scene"] }` config.
    const picker =
      input.target && typeof input.target === "object"
        ? (input.target as unknown as NodePickerConfig)
        : null;
    if (input.type === "scene_ref") {
      return { name: input.label || input.name, type: "entity_ref", options: [], picker_config: { sources: [{ kind: "manuscript" }] } };
    }
    return {
      name: input.label || input.name,
      type: input.type === "entity_ref_list" ? "entity_ref_list" : "entity_ref",
      options: [],
      picker_config: picker,
    };
  }

  function decodeRefValue(raw: string): string | string[] {
    if (input.type === "entity_ref_list") {
      try {
        const parsed = JSON.parse(raw || "[]");
        return Array.isArray(parsed) ? parsed.map(String) : [];
      } catch {
        return [];
      }
    }
    return raw || "";
  }

  function encodeRefValue(v: string | string[]): string {
    return Array.isArray(v) ? JSON.stringify(v) : (v ?? "");
  }

  function decodeContextPickValue(raw: string): NodePickerRef[] {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(
        (item): item is NodePickerRef =>
          item && typeof item === "object" && typeof item.id === "string" && typeof item.kind === "string",
      );
    } catch {
      return [];
    }
  }
</script>

{#if input.type === "long_text"}
  <PlainTextEditor
    value={value ?? ""}
    ariaLabel={ariaLabel ?? (input.label || input.name)}
    minHeight={60}
    maxHeight={200}
    matcher={implicitContextMatcher}
    onChange={onChange}
  />
{:else if input.type === "number"}
  <input
    type="number"
    value={value ?? ""}
    aria-label={ariaLabel}
    oninput={(e) => onChange((e.currentTarget as HTMLInputElement).value)}
  />
{:else if input.type === "boolean"}
  <!-- Tri-state: Unset / True / False. Unset is a real persisted state
       (#24, #42) — preview and runtime both treat it as undefined so the
       template can guard with `is defined` and fail fast otherwise.
       Replaces the 2-state checkbox that silently coerced "untouched"
       into `false` and disagreed with the preview. -->
  <select
    value={value ?? ""}
    aria-label={ariaLabel}
    onchange={(e) => onChange((e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="">Unset</option>
    <option value="true">True</option>
    <option value="false">False</option>
  </select>
{:else if input.type === "select"}
  <select
    value={value ?? ""}
    aria-label={ariaLabel}
    onchange={(e) => onChange((e.currentTarget as HTMLSelectElement).value)}
  >
    {#if !input.required}
      <option value="">(none)</option>
    {/if}
    {#each input.options ?? [] as option}
      <option value={option.value}>{option.label ?? option.value}</option>
    {/each}
  </select>
{:else if input.type === "entity_ref" || input.type === "entity_ref_list" || input.type === "scene_ref"}
  <ReferencePicker
    field={refStubField()}
    value={decodeRefValue(value)}
    excludeId={excludeId}
    ariaLabel={ariaLabel ?? (input.label || input.name)}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    onChange={(value) => onChange(encodeRefValue(value))}
  />
{:else if input.type === "context_pick"}
  <NodePicker
    config={(input.target ?? {}) as NodePickerConfig}
    value={decodeContextPickValue(value)}
    label={input.label || input.name || "Context"}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    on:change={(event) => onChange(JSON.stringify(event.detail.value))}
  />
{:else}
  <input
    type="text"
    value={value ?? ""}
    aria-label={ariaLabel}
    oninput={(e) => onChange((e.currentTarget as HTMLInputElement).value)}
  />
{/if}
