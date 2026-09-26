// Where a chat's Propose review lands (#2246). A revise commit publishes its
// review onto the subject's NodeEditor pane (the only surface that renders an
// `entryBrainstorm` proposal), so the chat resolves the subject id to that
// pane's opener and to a title the hand-off notice can name. One resolver for
// every revise subject kind with a document pane — lore, plotline, plot card,
// scene — rather than a lore-only branch per call site.
//
// A plotline is deliberately opened as its DOCUMENT (`openPlotline`), not
// revealed on the board like `openNodeOfKind` does: the board node never
// renders a review. A character arc has no document pane yet, so it resolves
// to null (notice-only), like any id not in the rosters.

import { findNodeBySceneId } from "@/lib/utils/treeHelpers";
import { structureNodeTitle } from "@/lib/utils/nodeTitle";
import type { MetadataSchema, StructureDocument } from "@/lib/types";

export interface CommitSubject {
  title: string;
  open: () => Promise<void>;
}

type Titled = { id: string; title: string };

export interface CommitSubjectRosters {
  lore: Titled[];
  plotlines: Titled[];
  cards: Titled[];
  structure: StructureDocument | null;
  schema: MetadataSchema | null | undefined;
}

export interface CommitSubjectOpeners {
  openLore: (id: string) => Promise<void>;
  openPlotline: (id: string) => Promise<void>;
  openPlotCard: (id: string) => Promise<void>;
  openScene: (id: string) => Promise<void>;
}

export function resolveCommitSubject(
  id: string,
  rosters: CommitSubjectRosters,
  openers: CommitSubjectOpeners,
): CommitSubject | null {
  // Method NAMES, called on `openers` — the host is the `editorPanes`
  // controller, whose openers use `this`; a detached reference loses it and
  // the swallowed TypeError opened nothing (#2251).
  const byRoster: [Titled[], keyof CommitSubjectOpeners][] = [
    [rosters.lore, "openLore"],
    [rosters.plotlines, "openPlotline"],
    [rosters.cards, "openPlotCard"],
  ];
  for (const [roster, opener] of byRoster) {
    const entry = roster.find((e) => e.id === id);
    if (entry) return { title: entry.title, open: () => openers[opener](id) };
  }
  // A scene's front-matter `id` IS its structure node's `scene_id` (#201).
  const sceneNode = rosters.structure ? findNodeBySceneId(rosters.structure.root, id) : null;
  if (sceneNode) return { title: structureNodeTitle(sceneNode, rosters.schema), open: () => openers.openScene(id) };
  return null;
}
