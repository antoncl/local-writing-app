// The disposition VALUES are computed backend-side since #1684
// (services/project/prompts.py, covered by backend test_prompt_disposition.py);
// what the frontend still owns is a handful of label/key constants named in
// code — the built-in view predicates and the chat seed lift. This test pins
// them to the shared vocabulary file so the two sides cannot drift.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  CHAT_DISPOSITION_LABEL,
  DISPOSITION_FIELD,
  REVISE_ENTITIES_DISPOSITION_LABEL,
  RUNNABLE_FIELD,
  RUNNABLE_VALUE,
} from "@/lib/views/promptNodes";
import { OUTPUT_HANDLER_KEYS } from "@/lib/editor-core/outputHandlers";

const here = dirname(fileURLToPath(import.meta.url));
const vocab = JSON.parse(
  readFileSync(resolve(here, "../../../../spec/prompt-disposition-labels.json"), "utf-8"),
);

describe("prompt disposition vocabulary parity (#1684)", () => {
  it("pins the field keys to the shared vocabulary", () => {
    expect(DISPOSITION_FIELD).toBe(vocab.disposition_field);
    expect(RUNNABLE_FIELD).toBe(vocab.runnable_field);
    expect(RUNNABLE_VALUE).toBe(vocab.runnable_value);
  });

  it("pins the labels the frontend names in code to the shared vocabulary", () => {
    expect(CHAT_DISPOSITION_LABEL).toBe(vocab.chat_label);
    expect(REVISE_ENTITIES_DISPOSITION_LABEL).toBe(vocab.revise_entities_label);
    // The named labels are members of the shelf-ordered set, at their shelf
    // positions — a rename or reorder must touch the vocabulary file, which
    // the backend suite asserts against too.
    expect(vocab.dispositions).toContain(vocab.chat_label);
    expect(vocab.dispositions).toContain(vocab.revise_entities_label);
    expect(vocab.dispositions).toHaveLength(5);
  });

  it("pins the handler registry to the shared vocabulary", () => {
    // The backend's disposition computation reads a closed copy of this set
    // (PROMPT_OUTPUT_HANDLER_KEYS); adding a handler to the registry without
    // teaching the backend would silently shelve its prompts under Snippets,
    // so the vocabulary file gates both sides.
    expect([...OUTPUT_HANDLER_KEYS]).toEqual(vocab.handlers);
  });
});
