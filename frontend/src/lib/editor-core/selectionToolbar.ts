// Shared types for ProseBodyView's floating selection toolbar.
// The host builds the action list (formatting commands + the AI "Revise"
// menu) and owns the menu open/position state; the presentational
// ProseSelectionToolbar component renders the buttons/menus from these.

export type FloatingMenuState = {
  visible: boolean;
  x: number;
  y: number;
  wordCount: number;
  placement: "above" | "below";
};

export type ToolbarButtonAction = {
  kind: "button";
  id: string;
  label: string;
  run: () => void | Promise<void>;
};

export type ToolbarMenuAction = {
  kind: "menu";
  id: string;
  label: string;
  items: Array<{
    id: string;
    label: string;
    run: () => void | Promise<void>;
  }>;
};

export type ToolbarAction = ToolbarButtonAction | ToolbarMenuAction;
