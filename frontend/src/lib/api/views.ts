import type { CreateViewRequest, SaveViewRequest, ViewNode, ViewNodeList, ViewUiState } from "@/lib/types";
import { request } from "./core";

export const viewsApi = {
  // Saved-view nodes (0.5.0 #78 backend / #80 designer). A view is a
  // frontmatter-only node carrying a ViewSpec; the designer (ViewBodyView)
  // reads getView and persists via saveView.
  listViews() {
    return request<ViewNodeList>("/views");
  },
  createView(payload: CreateViewRequest) {
    return request<ViewNode>("/views", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getView(viewId: string) {
    return request<ViewNode>(`/views/${encodeURIComponent(viewId)}`);
  },
  saveView(viewId: string, payload: SaveViewRequest) {
    return request<ViewNode>(`/views/${encodeURIComponent(viewId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  deleteView(viewId: string) {
    return request<ViewNodeList>(`/views/${encodeURIComponent(viewId)}`, {
      method: "DELETE",
    });
  },
  // Lock-free ui write (ADR-0036). MERGES the given fields into the view's `ui`
  // blob (a `view_default_<kind>` id with no file yet materializes the system
  // default). Pass only the field you own — `collapsed` (fold state) or
  // `appearance` (ADR-0069) — and the backend leaves the other untouched, so the
  // two independent writers never clobber each other.
  updateViewUi(viewId: string, ui: Partial<ViewUiState>) {
    return request<ViewNode>(`/views/${encodeURIComponent(viewId)}/ui`, {
      method: "PUT",
      body: JSON.stringify({ ui }),
    });
  },
};
