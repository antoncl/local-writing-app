// Marks the HTML the app's editors put on the clipboard, so a paste back into
// the app keeps its own inline nodes (#2235).
//
// `sanitizePastedHtml` strips every data-* attribute and unwraps every span,
// which is right for Word or Google Docs HTML but flattens the app's own
// inline nodes (a mutation pill, a character mention) into text. HTML carrying
// the marker is passed through instead. ProseMirror 1.42 has no
// transformCopiedHTML hook, so the marker is appended by the clipboard
// serializer, which is where the schema is known.
import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { DOMSerializer, type Fragment, type Schema } from "@tiptap/pm/model";
import { APP_CLIPBOARD_MARKER } from "@/lib/utils/sanitizePastedHtml";

/** The schema's DOM serializer, with an empty marker span after the copied content. */
export function appClipboardSerializer(schema: Schema): DOMSerializer {
  const base = DOMSerializer.fromSchema(schema);
  const serializer = new DOMSerializer(base.nodes, base.marks);
  const serializeFragment = serializer.serializeFragment.bind(serializer);
  serializer.serializeFragment = (
    fragment: Fragment,
    options: { document?: Document } = {},
    target?: HTMLElement | DocumentFragment,
  ) => {
    const out = serializeFragment(fragment, options, target);
    const marker = (options.document ?? document).createElement("span");
    marker.setAttribute(APP_CLIPBOARD_MARKER, "");
    out.appendChild(marker);
    return out;
  };
  return serializer;
}

export const AppClipboardMarker = Extension.create({
  name: "appClipboardMarker",
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey("appClipboardMarker"),
        props: { clipboardSerializer: appClipboardSerializer(this.editor.schema) },
      }),
    ];
  },
});
