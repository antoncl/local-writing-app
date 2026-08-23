// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import { reactive } from "@/lib/test/reactive.svelte";

// The dialog fetches the running app version (ADR-0072 S2) on first open —
// stub it so the mount is hermetic (#973's network guard fails any test that
// lets a real fetch through).
vi.mock("@/lib/api", () => ({
  api: {
    getVersion: vi.fn(async () => ({ version: "9.9.9" })),
  },
}));

import type { MachineSettingsDraft, MachineSettingsView } from "@/lib/types";
import type { AIHealthResponse } from "@/lib/aiTypes";
import MachineSettingsDialog from "@/components/dialogs/MachineSettingsDialog.svelte";

// The app-wide AI policy (#746) is deliberately NOT part of the batched draft:
// widening AI permission must be its own explicit gesture, never a side effect
// of the dialog's Save (decisions_ai_permission_fails_closed). These tests pin
// that contract — the rest of the dialog (providers/palette/storage) has its own
// coverage.

const DISPLAY = { ui_scale: 1.0, paragraph_align: "left" as const, paragraph_indent: false };

function view(ai_policy: MachineSettingsView["ai_policy"]): MachineSettingsView {
  return {
    version: 1,
    providers: { anthropic_api_key: "", openai_api_key: "", openrouter_api_key: "", ollama_host: "" },
    default_provider: "ollama",
    default_models: {},
    default_projects_folder: "",
    recent_projects: [],
    palette: [],
    display: DISPLAY,
    ai_policy,
    config_path: "C:/config.yaml",
  };
}

function draft(): MachineSettingsDraft {
  return {
    anthropic_api_key: "",
    openai_api_key: "",
    openrouter_api_key: "",
    ollama_host: "",
    default_provider: "ollama",
    default_models: {},
    default_projects_folder: "",
    palette: [],
    display: { ...DISPLAY },
  };
}

const radio = (name: string) => screen.getByRole("radio", { name }) as HTMLInputElement;
const applyBtn = () => screen.getByRole("button", { name: "Apply" }) as HTMLButtonElement;

function mount(ai_policy: MachineSettingsView["ai_policy"], onApplyPolicy = vi.fn().mockResolvedValue(true), onSave = vi.fn()) {
  render(MachineSettingsDialog, {
    props: {
      open: true,
      settings: view(ai_policy),
      draft: reactive(draft()),
      onCancel: () => {},
      onSave,
      onApplyPolicy,
      health: null,
    },
  });
  return { onApplyPolicy, onSave };
}

beforeEach(() => vi.clearAllMocks());

describe("MachineSettingsDialog — app-wide AI policy (#746)", () => {
  it("seeds the control from the persisted policy", () => {
    mount("cloud-allowed");
    expect(radio("Cloud allowed").checked).toBe(true);
    expect(radio("Off").checked).toBe(false);
  });

  it("disables Apply until the draft differs, then enables it", async () => {
    mount("off");
    expect(applyBtn().disabled).toBe(true); // nothing changed yet
    await fireEvent.click(radio("Cloud allowed"));
    expect(applyBtn().disabled).toBe(false);
  });

  it("a radio click alone never persists — only Apply commits", async () => {
    const { onApplyPolicy } = mount("off");
    await fireEvent.click(radio("Cloud allowed"));
    expect(onApplyPolicy).not.toHaveBeenCalled(); // fails closed

    await fireEvent.click(applyBtn());
    expect(onApplyPolicy).toHaveBeenCalledTimes(1);
    expect(onApplyPolicy).toHaveBeenCalledWith("cloud-allowed");
  });

  it("the dialog's Save never carries the policy — it is decoupled", async () => {
    const { onApplyPolicy, onSave } = mount("off");
    await fireEvent.click(radio("Cloud allowed")); // widen the draft
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledTimes(1); // the batched save ran
    expect(onApplyPolicy).not.toHaveBeenCalled(); // but the permission did NOT ride along
  });
});

describe("MachineSettingsDialog — health names the resolved assistant (#336)", () => {
  function mountHealth(result: AIHealthResponse) {
    render(MachineSettingsDialog, {
      props: {
        open: true,
        settings: view("cloud-allowed"),
        draft: reactive(draft()),
        onCancel: () => {},
        onSave: vi.fn(),
        onApplyPolicy: vi.fn().mockResolvedValue(true),
        health: { checking: false, disabledReason: null, onCheck: vi.fn(), result },
      },
    });
  }

  it("names the resolved assistant on a passing ping so the tick isn't ambiguous", () => {
    mountHealth({
      provider: "anthropic",
      model: "claude-haiku",
      ok: true,
      latency_ms: 5,
      policy: "cloud-allowed",
      assistant_id: "cheap",
      assistant_name: "Cheap",
    });
    const line = screen.getByText(/Cheap/);
    expect(line.textContent).toContain("✓");
    expect(line.textContent).toContain("Cheap");
    expect(line.textContent).toContain("anthropic");
  });

  it("names the assistant on a failing ping too, so a red ✗ says which one broke", () => {
    mountHealth({
      provider: "anthropic",
      model: "m",
      ok: false,
      latency_ms: 0,
      policy: "cloud-allowed",
      error: "Anthropic API key is not configured.",
      assistant_id: "creative",
      assistant_name: "Creative",
    });
    const line = screen.getByText(/Creative/);
    expect(line.textContent).toContain("✗");
    expect(line.textContent).toContain("Creative");
    expect(line.textContent).toContain("not configured");
  });
});

describe("MachineSettingsDialog — running app version (ADR-0072 S2)", () => {
  it("fetches and shows the running version once the dialog is open", async () => {
    mount("off");
    expect(await screen.findByText("Version 9.9.9")).toBeInTheDocument();
  });
});
