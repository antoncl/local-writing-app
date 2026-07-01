import { marked } from "marked";
import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  bulletListMarker: "-",
});

turndown.use(gfm);
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
    return `<!-- character:id=${id} -->${content}<!-- /character -->`;
  },
});
turndown.addRule("mutationMark", {
  filter: (node: Node) => {
    if (!(node instanceof HTMLElement)) return false;
    return node.tagName === "SPAN" && Boolean(node.dataset.mutationEntity);
  },
  replacement: (_content: string, node: Node) => {
    const element = node as HTMLElement;
    const entity = element.dataset.mutationEntity;
    const field = element.dataset.mutationField;
    const markerId = element.dataset.mutationId;
    if (!entity || !field || !markerId) return "";
    // Value is url-encoded so it survives the markdown round-trip (matches the
    // backend marker grammar + embedded-todo note encoding).
    const value = encodeURIComponent(element.dataset.mutationValue ?? "");
    return `<!-- mutate:entity=${entity};field=${field};value=${value};id=${markerId} -->`;
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
  const prepared = markEmbeddedMutations(markEmbeddedCharacters(markEmbeddedTodos(markdown || "")));
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
    /<!--\s*character:id=([A-Za-z0-9_-]+)\s*-->([\s\S]*?)<!--\s*\/character\s*-->/g,
    (_match, characterId: string, content: string) => {
      return `<span data-character="${escapeAttribute(characterId)}">${content}</span>`;
    },
  );
}

function markEmbeddedMutations(markdown: string): string {
  // A mutation marker is a self-contained point comment (no wrapped prose) →
  // an empty atom span the MutationMark node parses. Value is url-decoded into
  // the data attribute for display; turndown re-encodes it on save.
  return markdown.replace(
    /<!--\s*mutate:entity=([A-Za-z0-9_-]+);field=([A-Za-z0-9_.-]+);value=([^;\s]*);id=([A-Za-z0-9_-]+)\s*-->/g,
    (_match, entity: string, field: string, value: string, markerId: string) => {
      return (
        `<span data-mutation-entity="${escapeAttribute(entity)}"` +
        ` data-mutation-field="${escapeAttribute(field)}"` +
        ` data-mutation-value="${escapeAttribute(decodeNote(value))}"` +
        ` data-mutation-id="${escapeAttribute(markerId)}"></span>`
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
