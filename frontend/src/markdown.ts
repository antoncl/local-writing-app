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
turndown.addRule("simpleMarkdownTable", {
  filter: "table",
  replacement: (_content: string, node: Node) => {
    const table = node as HTMLTableElement;
    const rows = Array.from(table.rows).map((row) =>
      Array.from(row.cells).map((cell) => cleanTableCell(turndown.turndown(cell.innerHTML))),
    );
    if (rows.length === 0) return "";

    const columnCount = Math.max(...rows.map((row) => row.length));
    if (columnCount === 0) return "";

    const normalizedRows = rows.map((row) => padRow(row, columnCount));
    const header = normalizedRows[0];
    const bodyRows = normalizedRows.slice(1);
    const separator = Array.from({ length: columnCount }, () => "---");
    const markdownRows = [header, separator, ...bodyRows].map(formatTableRow);

    return `\n\n${markdownRows.join("\n")}\n\n`;
  },
});

export async function sceneMarkdownToHtml(markdown: string): Promise<string> {
  return (await marked.parse(markEmbeddedTodos(markdown || ""))) || "<p></p>";
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
