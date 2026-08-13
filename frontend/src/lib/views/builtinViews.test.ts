import { describe, expect, it } from "vitest";
import { builtinViews, builtinSpecFor, isBuiltinExtraViewId } from "./builtinViews";
import type { MetadataSchema } from "@/lib/types";

const CHAT_SCHEMA = {
  entry_types: { "chat:chat_session": { name: "Chat", kind: "chat" } },
  fields: {},
} as unknown as MetadataSchema;

describe("builtinViews (ADR-0051 S6 follow-up)", () => {
  it("ships two built-in views for chat: All chats + Openable", () => {
    const views = builtinViews("chat", CHAT_SCHEMA);
    expect(views.map((v) => v.title)).toEqual(["All chats", "Openable chats"]);
    // [0] is the roster default addressed by the fold-state id.
    expect(views[0].id).toBe("view_default_chat");
    // The extra is a synthesized built-in, recognised as a valid selection.
    expect(isBuiltinExtraViewId(views[1].id)).toBe(true);
    expect(isBuiltinExtraViewId(views[0].id)).toBe(false);
  });

  it("Openable filters out the committing (brainstorm) chats via disjoint", () => {
    const openable = builtinViews("chat", CHAT_SCHEMA)[1].spec;
    const pred = openable.expr?.filter?.pred?.field;
    expect(pred?.key).toBe("seed_committing");
    expect(pred?.op).toBe("disjoint");
    expect(pred?.value).toEqual(["commit"]);
  });

  it("every other kind ships a single default view (defaultView parity untouched)", () => {
    const lore = builtinViews("lore", null);
    expect(lore).toHaveLength(1);
    expect(lore[0].title).toBe("Default view");
    expect(lore[0].id).toBe("view_default_lore");
  });

  it("builtinSpecFor resolves a built-in id, else null", () => {
    expect(builtinSpecFor("chat", "view_builtin_chat_openable", CHAT_SCHEMA)).not.toBeNull();
    expect(builtinSpecFor("chat", "view_default_chat", CHAT_SCHEMA)).not.toBeNull();
    expect(builtinSpecFor("chat", "view_some_user_view", CHAT_SCHEMA)).toBeNull();
  });
});
