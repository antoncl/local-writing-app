<!--
  FieldsOnlyView — body-region slot for entry types whose body_shape is
  "none" (assistant / project / structure_node). Pre-redesign this is
  inert: the metadata + backlinks already live in the editor header, so
  the body region just collapses. Post-redesign target (see
  decisions-node-editor-body-spec, gap #1): render the metadata panel in
  the body column when the rail is the whole pane. Keeping the slot now
  means that future change touches one file.
-->
<div class="fields-only-view" aria-hidden="true"></div>

<style>
  .fields-only-view {
    display: none;
  }
</style>
