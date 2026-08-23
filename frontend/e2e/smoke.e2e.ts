import { test, expect } from "@playwright/test";
import { makeTempDir, openSeededProject } from "./helpers";

// Thin browser-E2E smoke (#1352): the assembled product boots in a real browser
// and the frontend↔backend wiring holds un-mocked. Boot-and-wiring only — never
// feature coverage. See #1351 for the rationale, playwright.config.ts for the two
// targets (built bundle + backend; frozen binary).

test.describe("assembled-product smoke (#1352)", () => {
  test("boots to the no-project state", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("no-project")).toBeVisible();
    await expect(page.getByRole("button", { name: /Open a project/ })).toBeVisible();
  });

  test("rehydrates into a pre-seeded open project", async ({ page, request }) => {
    await openSeededProject(page, request);
    // The workspace mounted (asserted in the helper) and the empty state is gone.
    await expect(page.getByTestId("no-project")).toHaveCount(0);
  });

  test("creates a project through the wizard", async ({ page }) => {
    // The wizard builds the project folder under this parent from the name.
    const parent = makeTempDir();
    await page.goto("/");
    await page.getByRole("button", { name: /Open a project/ }).click();
    await page.getByRole("menuitem", { name: /New project/ }).click();

    await page.getByTestId("wizard-project-name").fill("Wizard Smoke");
    await page.getByTestId("wizard-project-folder").fill(parent);

    // Step through the wizard to the end and create. Stepping (not assuming a
    // fixed step count) keeps this robust if steps are added/removed.
    const createButton = page.getByRole("button", { name: /^Create/ });
    for (let i = 0; i < 6 && (await createButton.count()) === 0; i++) {
      await page.getByRole("button", { name: /^Next/ }).click();
    }
    await createButton.click();

    await expect(page.getByTestId("workspace")).toBeVisible();
  });

  test("types into a scene and it autosaves", async ({ page, request }) => {
    const { scene } = await openSeededProject(page, request, { sceneTitle: "Chapter One" });

    // Open the seeded scene from the Draft tree: click the row's title button
    // (`.node-row-click`), not the drag handle or delete control beside it.
    await page.locator(".node-row").filter({ hasText: "Chapter One" }).locator(".node-row-click").click();

    const prose = page.getByTestId("prose-editor").locator(".ProseMirror");
    await expect(prose).toBeVisible();

    // Arm the save assertion before typing: the editor↔backend write is the
    // richest wiring path — a real PUT to this scene must round-trip.
    const saved = page.waitForResponse(
      (r) => r.request().method() === "PUT" && r.url().includes(`/api/scenes/${scene!.id}`),
    );
    await prose.click();
    await prose.pressSequentially("The wiring holds.");
    const res = await saved;
    expect(res.ok()).toBeTruthy();
  });

  test("opens the settings dialog", async ({ page, request }) => {
    await openSeededProject(page, request);
    await page.getByRole("button", { name: "Application menu" }).click();
    await page.getByRole("menuitem", { name: /Settings/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});
