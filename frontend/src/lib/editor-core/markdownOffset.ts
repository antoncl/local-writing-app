// A ProseMirror doc position → scene-markdown char offset (ADR-0089 §4): the
// /mutate dialog's baseline now resolves at its OWN insertion position rather
// than always the end of the scene, reversing #74's deviation for the dialog
// only. Serializes the doc slice BEFORE `pos` exactly as the editor itself
// serializes on save (`editorHtmlToSceneMarkdown(editor.getHTML())`,
// ProseBodyView's `getBody`) — just over `doc.cut(0, pos)` instead of the
// whole doc — so the mapped offset lines up with what the scene body will
// actually read at save time. Pure over a doc + schema so it's isolable from
// the live `Editor` for a unit test.
import { getHTMLFromFragment } from "@tiptap/core";
import type { Node as ProseMirrorNode, Schema } from "@tiptap/pm/model";
import { editorHtmlToSceneMarkdown } from "@/lib/utils/markdown";

export function markdownOffsetAt(doc: ProseMirrorNode, schema: Schema, pos: number): number {
  const clamped = Math.max(0, Math.min(pos, doc.content.size));
  const html = getHTMLFromFragment(doc.cut(0, clamped).content, schema);
  return editorHtmlToSceneMarkdown(html).length;
}
