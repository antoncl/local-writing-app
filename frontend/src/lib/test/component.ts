// Shared harness for Svelte component tests (#642).
//
// The frontend's ~53 other vitest files are pure logic (stores / utils /
// views) and run in vitest's default `node` environment. This harness is the
// opt-in path for the *other* kind of test — mounting a real `.svelte`
// component and asserting on what it renders and how it reacts — the gap that
// let the #639 reseed bug ship unguarded.
//
// A component test opts in with two lines, and never touches the shared config:
//
//     // @vitest-environment happy-dom          <- must be the file's first line
//     import { render, screen, fireEvent } from "@/lib/test/component";
//
// Importing this module registers jest-dom's matchers (`toBeInTheDocument`,
// `toBeChecked`, …) and Testing Library's auto-cleanup between tests. It only
// runs for files that import it — i.e. only under happy-dom — so the node
// suite is unaffected.
//
// Scope: plain, logic-bearing components (rows, lists, modals, controlled
// widgets). NOT the rich editors — TipTap / CodeMirror / SvelteFlow need heavy
// or canvas DOM that happy-dom doesn't provide (SvelteFlow renders zero edges
// headless). Cover those via their extracted logic + real-browser checks.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/svelte";

afterEach(cleanup);

export { render, screen, fireEvent, within } from "@testing-library/svelte";
