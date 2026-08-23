import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

// The localStorage key the SPA reads on mount to re-open the last project
// (projectSession.rehydrate → openProjectAt). Seeding it lets a fresh browser
// land directly in an open workspace with no wizard clicks.
export const LAST_PROJECT_KEY = "lastOpenedProjectPath";

// A fresh, empty folder on the runner the backend can write a project into. The
// backend creates a project *at* this path, so it must already exist.
export function makeTempDir(prefix = "lwa-e2e-"): string {
  return mkdtempSync(join(tmpdir(), prefix));
}

// The wire scope every scoped request carries (#413): the backend reads the open
// project's root from this header, URL-encoded exactly as api.ts sends it.
function scopeHeaders(root: string): Record<string, string> {
  return { "X-Project-Root": encodeURIComponent(root) };
}

// Create a project on disk via the real API (the same POST the wizard fires).
// `create` establishes scope from the body, so it needs no scope header.
export async function createProjectViaApi(
  request: APIRequestContext,
  rootPath: string,
  title = "E2E Smoke",
): Promise<{ root_path: string }> {
  const res = await request.post("/api/project/create", {
    data: { root_path: rootPath, title },
  });
  expect(res.ok(), `create project → ${res.status()}: ${await res.text()}`).toBeTruthy();
  return res.json();
}

// Seed the machine's default projects folder (isolated per playwright.config.ts),
// so the create wizard opens on its "location" step rather than the first-run
// "root" step that appears when no folder is set. The folder must already exist —
// the backend validates it (#429).
export async function setDefaultProjectsFolder(
  request: APIRequestContext,
  folder: string,
): Promise<void> {
  const res = await request.put("/api/settings/machine", {
    data: { default_projects_folder: folder },
  });
  expect(res.ok(), `set default projects folder → ${res.status()}: ${await res.text()}`).toBeTruthy();
}

// Add a scene to an open project via the API, so a scene-editor flow has
// something to open without driving the structure tree.
export async function createSceneViaApi(
  request: APIRequestContext,
  rootPath: string,
  title: string,
): Promise<{ id: string; title: string }> {
  const res = await request.post("/api/scenes", {
    headers: scopeHeaders(rootPath),
    data: { title },
  });
  expect(res.ok(), `create scene → ${res.status()}: ${await res.text()}`).toBeTruthy();
  return res.json();
}

// Land the browser in an open project: create it (and optionally a scene) via the
// API, seed the last-opened key, then load so rehydrate() opens it. Returns the
// project root and any created scene. The `[data-testid="workspace"]` sentinel is
// the honest "the tiled workspace mounted" signal.
export async function openSeededProject(
  page: Page,
  request: APIRequestContext,
  opts: { sceneTitle?: string } = {},
): Promise<{ root: string; scene?: { id: string; title: string } }> {
  const root = makeTempDir();
  await createProjectViaApi(request, root);
  const scene = opts.sceneTitle
    ? await createSceneViaApi(request, root, opts.sceneTitle)
    : undefined;
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [LAST_PROJECT_KEY, root] as const,
  );
  await page.goto("/");
  await expect(page.getByTestId("workspace")).toBeVisible();
  return { root, scene };
}
