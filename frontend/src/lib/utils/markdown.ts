import { marked } from "marked";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  bulletListMarker: "-",
  // Scene breaks (#1239): pin the on-disk representation of an <hr> to the
  // conventional fiction dinkus rather than leaving it to the library default,
  // so a `---` input rule and an inserted rule both settle to `* * *`.
  hr: "* * *",
});

turndown.use(gfm);
// Emit clean list markdown (`- item`, `1. item`) instead of turndown's padded
// default (`-   item` / `1.  item`, #1619). The padding is invisible when
// rendered but differs from the AI's `- item` on every line, so a padded body
// diffed against an AI revise stacked whole blocks (#1617 handles the display;
// this fixes the source). Added AFTER gfm so its task-list rule still wins for
// checkbox items; this only claims plain `<li>`. Continuation lines indent by
// the marker width, so nested lists and multi-block items stay well-formed.
turndown.addRule("listItem", {
  filter: "li",
  replacement: (content: string, node: Node): string => {
    const element = node as HTMLElement;
    const parent = element.parentNode as HTMLElement | null;
    let prefix: string;
    if (parent && parent.nodeName === "OL") {
      const startAttr = parent.getAttribute("start");
      const index = Array.prototype.indexOf.call(parent.children, element);
      prefix = `${startAttr ? Number(startAttr) + index : index + 1}. `;
    } else {
      prefix = "- ";
    }
    const indent = " ".repeat(prefix.length);
    const body = content
      .replace(/^\n+/, "")
      .replace(/\n+$/, "\n")
      .replace(/\n/gm, `\n${indent}`);
    return prefix + body + (element.nextSibling && !/\n$/.test(body) ? "\n" : "");
  },
});
turndown.addRule("todoAnchor", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    return node.tagName === "SPAN" && Boolean(node.dataset.todoId);
  },
  replacement: (content: string, node: Node) => {
    const element = node as HTMLElement;
    const todoId = element.dataset.todoId;
    if (!todoId) return content;
    const status = element.dataset.todoStatus === "done" ? "done" : "open";
    const note = encodeURIComponent(element.dataset.todoNote ?? "");
    return `<!-- embedded-todo:id=${todoId};status=${status};note=${note} -->${content}<!-- /embedded-todo -->`;
  },
});
turndown.addRule("characterMark", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    return node.tagName === "SPAN" && Boolean(node.dataset.character);
  },
  replacement: (content: string, node: Node) => {
    const element = node as HTMLElement;
    const id = element.dataset.character;
    if (!id) return content;
    // ADR-0070: a beat may carry its character's private interiority as an
    // optional `;internal=<url-encoded>` field. Absent when empty, so plain
    // beats keep their old marker shape.
    const internal = element.dataset.internal ?? "";
    const suffix = internal ? `;internal=${encodeURIComponent(internal)}` : "";
    return `<!-- character:id=${id}${suffix} -->${content}<!-- /character -->`;
  },
});
turndown.addRule("mutationMark", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    // A close pill also carries `data-mutation-id` (its own close id) but is
    // told apart by `data-mutation-close-ref`; check for THAT absence, not
    // presence of `data-mutation-set` — a copy-in-flight pill (ADR-0095 §7)
    // clears its `setId` and would otherwise serialize as nothing.
    return node.tagName === "SPAN" && Boolean(node.dataset.mutationId) && !node.dataset.mutationCloseRef;
  },
  replacement: (_content: string, node: Node) => {
    const element = node as HTMLElement;
    const anchorId = element.dataset.mutationId;
    const setId = element.dataset.mutationSet ?? "";
    if (!anchorId) return "";
    // ADR-0095 §1: the anchor names its SET and nothing else — no entity,
    // rows or name in the prose (the anti-goal against a second copy of the
    // set's values going stale).
    return `<!-- mutate:set=${setId};id=${anchorId} -->`;
  },
});
turndown.addRule("mutationCloseMark", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    return node.tagName === "SPAN" && Boolean(node.dataset.mutationCloseRef);
  },
  replacement: (_content: string, node: Node) => {
    const element = node as HTMLElement;
    const ref = element.dataset.mutationCloseRef;
    const closeId = element.dataset.mutationId;
    if (!ref || !closeId) return "";
    const row = element.dataset.mutationCloseRow ?? "";
    const rowPart = row ? `;row=${row}` : "";
    return `<!-- mutate:close;ref=${ref}${rowPart};id=${closeId} -->`;
  },
});
turndown.addRule("simpleMarkdownTable", {
  filter: "table",
  replacement: (_content: string, node: Node) => {
    const table = node as HTMLTableElement;
    const cellRows = Array.from(table.rows);
    if (cellRows.length === 0) return "";

    const textRows = cellRows.map((row) =>
      Array.from(row.cells).map((cell) => cleanTableCell(turndown.turndown(cell.innerHTML))),
    );
    const columnCount = Math.max(...textRows.map((row) => row.length));
    if (columnCount === 0) return "";

    const alignments = Array.from({ length: columnCount }, (_, colIndex) => {
      for (const row of cellRows) {
        const cell = row.cells[colIndex] as HTMLElement | undefined;
        if (!cell) continue;
        const value = (cell.style.textAlign || cell.getAttribute("align") || "").toLowerCase();
        if (value) return value;
      }
      return "";
    });

    const normalizedRows = textRows.map((row) => padRow(row, columnCount));
    const header = normalizedRows[0];
    const bodyRows = normalizedRows.slice(1);
    const separator = alignments.map((align) => {
      if (align === "center") return ":---:";
      if (align === "right") return "---:";
      if (align === "left") return ":---";
      return "---";
    });
    const markdownRows = [header, separator, ...bodyRows].map(formatTableRow);

    return `\n\n${markdownRows.join("\n")}\n\n`;
  },
});

export async function sceneMarkdownToHtml(markdown: string): Promise<string> {
  const prepared = markEmbeddedMutationCloses(
    markEmbeddedMutations(markEmbeddedCharacters(markEmbeddedTodos(markdown || ""))),
  );
  return (await marked.parse(prepared)) || "<p></p>";
}

export function editorHtmlToSceneMarkdown(html: string): string {
  return turndown.turndown(html).trim();
}

function padRow(row: string[], columnCount: number): string[] {
  return [...row, ...Array.from({ length: columnCount - row.length }, () => "")];
}

function formatTableRow(cells: string[]): string {
  return `| ${cells.join(" | ")} |`;
}

function cleanTableCell(value: string): string {
  return value.replace(/\s+/g, " ").replace(/\|/g, "\\|").trim();
}

function markEmbeddedTodos(markdown: string): string {
  const migrated = markdown.replace(
    /<!--\s*todo-anchor:id=([A-Za-z0-9_-]+)\s*-->([\s\S]*?)<!--\s*\/todo-anchor\s*-->/g,
    (_match, todoId: string, content: string) => {
      return `<span data-todo-id="${escapeAttribute(todoId)}" data-todo-status="open" data-todo-note="">${content}</span>`;
    },
  );

  return migrated.replace(
    /<!--\s*embedded-todo:id=([A-Za-z0-9_-]+);status=(open|done);note=([^]*?)\s*-->([\s\S]*?)<!--\s*\/embedded-todo\s*-->/g,
    (_match, todoId: string, status: string, note: string, content: string) => {
      return `<span data-todo-id="${escapeAttribute(todoId)}" data-todo-status="${status}" data-todo-note="${escapeAttribute(decodeNote(note))}">${content}</span>`;
    },
  );
}

function markEmbeddedCharacters(markdown: string): string {
  return markdown.replace(
    /<!--\s*character:id=([A-Za-z0-9_-]+)(?:;internal=(\S*))?\s*-->([\s\S]*?)<!--\s*\/character\s*-->/g,
    (_match, characterId: string, internal: string | undefined, content: string) => {
      // ADR-0070: decode the optional interiority payload onto data-internal so
      // the character mark carries it back into the editor (kept hidden — no UI
      // until S2). Mirrors the turndown rule above.
      const internalAttr = internal
        ? ` data-internal="${escapeAttribute(decodeNote(internal))}"`
        : "";
      return `<span data-character="${escapeAttribute(characterId)}"${internalAttr}>${content}</span>`;
    },
  );
}

function mutationSpan(setId: string, anchorId: string): string {
  const setAttr = setId ? ` data-mutation-set="${escapeAttribute(setId)}"` : "";
  return `<span${setAttr} data-mutation-id="${escapeAttribute(anchorId)}"></span>`;
}

function markEmbeddedMutations(markdown: string): string {
  // A mutation anchor is a self-contained point comment (no wrapped prose,
  // ADR-0095 §1) → an empty atom span the MutationMark node parses. The
  // anchor names its set and nothing else — no entity/rows/name in the
  // prose (the set node is the readable record now).
  return markdown.replace(
    /<!--\s*mutate:set=([A-Za-z0-9_-]*);id=([A-Za-z0-9_-]+)\s*-->/g,
    (_match, setId: string, anchorId: string) => mutationSpan(setId, anchorId),
  );
}

function markEmbeddedMutationCloses(markdown: string): string {
  // Interval-close marker (#59, ADR-0095 §1): a self-contained point comment
  // → empty atom span the MutationClose node parses. `row=` is optional (a
  // close on the whole anchor's set vs. one row of it); distinct grammar
  // (`close;ref=`) from a start anchor, so this runs after
  // markEmbeddedMutations without overlap.
  return markdown.replace(
    /<!--\s*mutate:close;ref=([A-Za-z0-9_-]+)(?:;row=([A-Za-z0-9_-]+))?;id=([A-Za-z0-9_-]+)\s*-->/g,
    (_match, ref: string, row: string | undefined, closeId: string) => {
      const rowAttr = row ? ` data-mutation-close-row="${escapeAttribute(row)}"` : "";
      return (
        `<span data-mutation-close-ref="${escapeAttribute(ref)}"` +
        rowAttr +
        ` data-mutation-id="${escapeAttribute(closeId)}"></span>`
      );
    },
  );
}

function decodeNote(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return "";
  }
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
